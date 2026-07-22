"""
VMware vSphere service — Linux VM discovery and inventory synchronisation.

Phase 4: multi-vCenter support.
  • VmwareService.from_connection(conn) accepts a VmwareConnection row.
  • Per-connection sync locks (dict keyed by connection.id).
  • sync_connection(app, connection_id, triggered_by) — sync one vCenter.
  • sync_all_connections(app, triggered_by) — loop all enabled connections.
  • Cross-vCenter deduplication: before marking stale, checks other connections.
  • Stale handling: a VM is only marked inactive when absent from ALL connections.

Performance design (unchanged):
  • Pre-loads ALL servers + meta in 3 queries before the upsert loop.
  • Accumulates all upserts in one transaction; commits once at the end.
  • Per-VM audit entries flushed with the batch commit.

Deduplication priority (unchanged):
  1. vmware_vm_uuid  (vm.config.uuid)
  2. bios_uuid       (vm.config.locationId)
  3. hostname
"""
from __future__ import annotations

import logging
import ssl
import threading
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── Per-connection sync locks ─────────────────────────────────────────────── #
# Protected by _locks_mutex; created on demand.
_conn_locks: dict[int, threading.Lock] = {}
_locks_mutex = threading.Lock()

# Keep a module-level lock alias so legacy callers still work
_sync_lock = threading.Lock()   # legacy — not used in Phase 4 paths

# Keywords in VMware guestId that indicate a Linux guest
_LINUX_GUEST_KEYWORDS = (
    "rhel", "centos", "fedora", "ubuntu", "debian", "sles",
    "opensuse", "oracle", "rocky", "alma", "amazon", "asianux",
    "mandrake", "redhat", "other24xlinux", "other26xlinux",
    "other3xlinux", "otherlinux", "linux",
)

_VCLS_PREFIX = "vCLS"


def _get_conn_lock(connection_id: int) -> threading.Lock:
    """Return (creating if needed) the per-connection sync lock."""
    with _locks_mutex:
        if connection_id not in _conn_locks:
            _conn_locks[connection_id] = threading.Lock()
        return _conn_locks[connection_id]


def is_sync_running(connection_id: int | None = None) -> bool:
    """
    Return True if a VMware sync is currently active.

    Args:
        connection_id: if given, checks only that connection.
                       If None, returns True if ANY connection is syncing.
    """
    if connection_id is not None:
        lock = _conn_locks.get(connection_id)
        return lock is not None and lock.locked()
    return any(lock.locked() for lock in _conn_locks.values())


class VmwareConnectionError(Exception):
    """Raised when a vCenter connection or authentication attempt fails."""


class VmwareService:
    """High-level interface to the VMware vSphere API for LOP."""

    def __init__(
        self,
        vcenter_host: str,
        port: int,
        username: str,
        password: str,
        ignore_ssl: bool = False,
        connection_name: str = "",
        connection_id: int | None = None,
    ):
        self.vcenter_host    = vcenter_host
        self.port            = port
        self.username        = username
        self.password        = password
        self.ignore_ssl      = ignore_ssl
        self.connection_name = connection_name or vcenter_host
        self.connection_id   = connection_id

    @classmethod
    def from_config(cls, cfg) -> "VmwareService":
        """Build from a legacy VmwareConfig or a VmwareConnection row."""
        conn_name = getattr(cfg, "name", None) or cfg.vcenter_host or ""
        conn_id   = cfg.id if hasattr(cfg, "id") and type(cfg).__name__ == "VmwareConnection" else None
        return cls(
            vcenter_host    = cfg.vcenter_host or "",
            port            = cfg.port or 443,
            username        = cfg.username or "",
            password        = cfg.get_password() or "",
            ignore_ssl      = cfg.ignore_ssl,
            connection_name = conn_name,
            connection_id   = conn_id,
        )

    @classmethod
    def from_connection(cls, conn) -> "VmwareService":
        """Build from a VmwareConnection model instance."""
        return cls(
            vcenter_host    = conn.vcenter_host or "",
            port            = conn.port or 443,
            username        = conn.username or "",
            password        = conn.get_password() or "",
            ignore_ssl      = conn.ignore_ssl,
            connection_name = conn.name or conn.vcenter_host or "",
            connection_id   = conn.id,
        )

    # ── Connection ────────────────────────────────────────────────────────── #

    def _ssl_context(self):
        if self.ignore_ssl:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        return None

    def _connect(self):
        try:
            from pyVim.connect import SmartConnect  # type: ignore
        except ImportError:
            raise VmwareConnectionError(
                "pyVmomi is not installed. Run: pip install pyVmomi"
            )

        ctx = self._ssl_context()
        try:
            return SmartConnect(
                host=self.vcenter_host,
                user=self.username,
                pwd=self.password,
                port=self.port,
                sslContext=ctx,
                connectionPoolTimeout=30,
            )
        except Exception as exc:
            msg = str(exc).lower()
            if any(k in msg for k in ("incorrect user name", "authentication", "login", "password")):
                raise VmwareConnectionError(
                    "Authentication Failed: Invalid username or password."
                )
            if any(k in msg for k in ("ssl", "certificate", "handshake", "verify")):
                raise VmwareConnectionError(
                    "SSL Error: Certificate verification failed. "
                    "Enable 'Ignore Invalid SSL Certificate' for self-signed certificates."
                )
            if any(k in msg for k in ("timeout", "timed out", "connect")):
                raise VmwareConnectionError(
                    f"Connection Timeout: Could not reach {self.vcenter_host}:{self.port}"
                )
            raise VmwareConnectionError(
                f"Disconnected: Could not connect to {self.vcenter_host}:{self.port}"
            )

    def test_connection(self) -> tuple[bool, str, str]:
        """Test vCenter connectivity. Returns (success, message, status_string)."""
        try:
            from pyVim.connect import Disconnect  # type: ignore
        except ImportError:
            return False, "pyVmomi not installed. Run: pip install pyVmomi", "Disconnected"

        si = None
        try:
            si = self._connect()
            about = si.RetrieveContent().about
            msg = f"Connected — {about.fullName} (API {about.apiVersion})"
            return True, msg, "Connected"
        except VmwareConnectionError as exc:
            status = str(exc).split(":")[0].strip()
            if status not in ("Authentication Failed", "SSL Error", "Connection Timeout"):
                status = "Disconnected"
            return False, str(exc), status
        except Exception:
            return False, f"Disconnected: Could not connect to {self.vcenter_host}", "Disconnected"
        finally:
            if si:
                try:
                    from pyVim.connect import Disconnect  # type: ignore
                    Disconnect(si)
                except Exception:
                    pass

    # ── Sync orchestration (single connection) ────────────────────────────── #

    def sync_now(self, app, triggered_by: str = "manual") -> tuple[bool, str]:
        """
        Trigger a background sync for THIS connection.
        Returns (started, message).
        """
        conn_id = self.connection_id
        if conn_id is not None:
            lock = _get_conn_lock(conn_id)
            if not lock.acquire(blocking=False):
                return False, f"Sync already running for '{self.connection_name}'."
        else:
            # Legacy path (no connection_id)
            if not _sync_lock.acquire(blocking=False):
                return False, "A sync is already in progress."

        thread = threading.Thread(
            target=self._do_sync,
            args=(app, triggered_by),
            daemon=True,
            name=f"vmware-sync-{conn_id or 'legacy'}",
        )
        thread.start()
        return True, "Sync started."

    def _do_sync(self, app, triggered_by: str) -> None:
        """Background sync worker. Runs inside a fresh Flask app context."""
        with app.app_context():
            from ..extensions import db
            from ..models.vmware_config import VmwareSyncLog
            from ..models.vmware_connection import VmwareConnection
            from ..models.server import Server
            from ..models.vmware_server_meta import VmwareServerMeta
            from ..audit import log_action, commit_audit

            conn_id = self.connection_id

            # ── Create sync log (running) ─────────────────────────────────── #
            log = VmwareSyncLog(
                connection_id=conn_id,
                status="running",
                started_at=datetime.now(timezone.utc),
                triggered_by=triggered_by,
            )
            db.session.add(log)
            db.session.commit()
            log_id = log.id

            # Reload connection record
            conn_rec = VmwareConnection.query.get(conn_id) if conn_id else None
            t0 = time.monotonic()
            si = None
            imported = updated = skipped = stale_marked = 0

            try:
                log_action(
                    "vmware.sync.started",
                    details=f"vcenter={self.vcenter_host} triggered_by={triggered_by}",
                )
                db.session.commit()

                si = self._connect()
                vms = self._collect_linux_vms(si)
                logger.info(
                    "VMware [%s]: discovered %d Linux VMs",
                    self.connection_name, len(vms),
                )

                # ── Pre-load all existing servers (3 queries) ─────────────── #
                all_servers: list[Server] = Server.query.all()
                vmware_servers_for_conn: list[Server] = [
                    s for s in all_servers
                    if s.source == "vmware" and (
                        # Only manage servers associated with this connection
                        not conn_id
                        or _server_belongs_to_conn(s, conn_id)
                    )
                ]
                all_meta: list[VmwareServerMeta] = VmwareServerMeta.query.all()

                by_uuid:     dict[str, Server]           = {}
                by_bios:     dict[str, Server]           = {}
                by_hostname: dict[str, Server]           = {}
                meta_by_sid: dict[int, VmwareServerMeta] = {}

                for s in all_servers:
                    by_hostname[s.hostname] = s
                    if s.vmware_vm_uuid:
                        by_uuid[s.vmware_vm_uuid] = s

                for m in all_meta:
                    meta_by_sid[m.server_id] = m
                    if m.bios_uuid:
                        srv = next((s for s in all_servers if s.id == m.server_id), None)
                        if srv:
                            by_bios[m.bios_uuid] = srv

                # Build set of all UUIDs managed by OTHER connections
                # (used for cross-vCenter stale detection)
                other_conn_uuids: set[str] = {
                    m.vm_uuid
                    for m in all_meta
                    if m.vm_uuid and m.connection_id != conn_id
                }

                synced_vm_uuids: set[str] = set()

                # ── Upsert each discovered VM ─────────────────────────────── #
                cfg_like = conn_rec  # used for default_location / default_environment
                for vm_data in vms:
                    try:
                        res = self._upsert_server(
                            db, vm_data, cfg_like,
                            by_uuid, by_bios, by_hostname, meta_by_sid,
                            connection_id=conn_id,
                            vcenter_name=self.connection_name,
                        )
                        if vm_data["vm_uuid"]:
                            synced_vm_uuids.add(vm_data["vm_uuid"])

                        if res == "imported":
                            imported += 1
                            log_action(
                                "vmware.vm.imported",
                                target=vm_data.get("hostname", ""),
                                details=f"vcenter={self.connection_name} vm={vm_data.get('vm_name', '')}",
                            )
                        elif res == "updated":
                            updated += 1
                        elif res == "duplicate":
                            log_action(
                                "vmware.vm.duplicate",
                                target=vm_data.get("hostname", ""),
                                details=(
                                    f"VM '{vm_data.get('vm_name', '')}' uuid={vm_data.get('vm_uuid','')} "
                                    f"already known from another vCenter — kept existing record"
                                ),
                            )
                            skipped += 1
                        else:
                            skipped += 1
                    except Exception as exc:
                        logger.warning(
                            "VMware [%s]: failed to upsert %s: %s",
                            self.connection_name, vm_data.get("vm_name"), exc,
                        )
                        db.session.rollback()
                        skipped += 1

                # ── Mark stale VMware servers inactive ────────────────────── #
                # A server is stale if:
                #   1. It was previously imported from THIS connection
                #   2. Its UUID was NOT seen in this sync
                #   3. Its UUID is NOT present in any OTHER connection's meta
                for srv in vmware_servers_for_conn:
                    if not srv.vmware_vm_uuid:
                        continue
                    if srv.vmware_vm_uuid in synced_vm_uuids:
                        continue  # healthy
                    if srv.vmware_vm_uuid in other_conn_uuids:
                        # Present in another vCenter — don't mark inactive
                        logger.debug(
                            "VMware: server %s uuid=%s still present in another connection",
                            srv.hostname, srv.vmware_vm_uuid,
                        )
                        continue
                    if srv.status == "active":
                        srv.status = "inactive"
                        log_action(
                            "vmware.vm.stale",
                            target=srv.hostname,
                            details=(
                                f"VM no longer in vCenter '{self.connection_name}' "
                                "and absent from all others — marked inactive"
                            ),
                        )
                        stale_marked += 1

                # ── Single batch commit ───────────────────────────────────── #
                db.session.commit()
                duration = time.monotonic() - t0

                # Update sync log
                log = VmwareSyncLog.query.get(log_id)
                if log:
                    log.status       = "completed"
                    log.finished_at  = datetime.now(timezone.utc)
                    log.vms_imported = imported
                    log.vms_updated  = updated
                    log.vms_skipped  = skipped

                # Update connection stats
                if conn_rec:
                    conn_rec = db.session.merge(conn_rec)
                    conn_rec.last_sync_at        = datetime.now(timezone.utc)
                    conn_rec.last_sync_ok_at     = datetime.now(timezone.utc)
                    conn_rec.last_sync_vms       = imported + updated
                    conn_rec.last_sync_duration_s = round(duration, 2)

                db.session.commit()
                commit_audit(
                    "vmware.sync.completed",
                    details=(
                        f"vcenter={self.connection_name} "
                        f"imported={imported} updated={updated} "
                        f"skipped={skipped} stale_marked={stale_marked} "
                        f"duration={duration:.1f}s"
                    ),
                )
                logger.info(
                    "VMware [%s] sync done: %d imported, %d updated, "
                    "%d skipped, %d stale (%.1fs)",
                    self.connection_name, imported, updated, skipped, stale_marked, duration,
                )

            except Exception as exc:
                duration = time.monotonic() - t0
                logger.error(
                    "VMware [%s] sync failed: %s",
                    self.connection_name, exc, exc_info=True,
                )
                try:
                    db.session.rollback()
                    log = VmwareSyncLog.query.get(log_id)
                    if log:
                        log.status        = "failed"
                        log.finished_at   = datetime.now(timezone.utc)
                        log.vms_imported  = imported
                        log.vms_updated   = updated
                        log.vms_skipped   = skipped
                        log.error_message = str(exc)[:1000]
                    if conn_rec:
                        conn_rec = db.session.merge(conn_rec)
                        conn_rec.last_sync_at      = datetime.now(timezone.utc)
                        conn_rec.last_sync_fail_at = datetime.now(timezone.utc)
                    db.session.commit()
                    commit_audit(
                        "vmware.sync.failed",
                        details=f"vcenter={self.connection_name} error={str(exc)[:400]}",
                    )
                except Exception:
                    logger.exception("VMware: failed to update sync log after failure")
            finally:
                if si:
                    try:
                        from pyVim.connect import Disconnect  # type: ignore
                        Disconnect(si)
                    except Exception:
                        pass
                # Release per-connection lock
                if self.connection_id is not None:
                    lock = _conn_locks.get(self.connection_id)
                    if lock and lock.locked():
                        try:
                            lock.release()
                        except Exception:
                            pass
                else:
                    try:
                        _sync_lock.release()
                    except Exception:
                        pass

    # ── VM discovery ──────────────────────────────────────────────────────── #

    def _collect_linux_vms(self, si) -> list[dict[str, Any]]:
        from pyVmomi import vim  # type: ignore
        content = si.RetrieveContent()
        view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.VirtualMachine], True
        )
        results = []
        try:
            for vm in view.view:
                try:
                    data = self._extract_vm_data(vm)
                    if data:
                        results.append(data)
                except Exception as exc:
                    logger.debug("VMware: skipping VM: %s", exc)
        finally:
            view.Destroy()
        return results

    @staticmethod
    def _is_linux(vm) -> bool:
        if vm.config is None or vm.config.template:
            return False
        try:
            family = (getattr(vm.guest, "guestFamily", "") or "").lower()
            if family == "linuxguest":
                return True
        except Exception:
            pass
        guest_id = (vm.config.guestId or "").lower()
        return any(kw in guest_id for kw in _LINUX_GUEST_KEYWORDS)

    @staticmethod
    def _is_windows(vm) -> bool:
        try:
            family = (getattr(vm.guest, "guestFamily", "") or "").lower()
            if family == "windowsguest":
                return True
        except Exception:
            pass
        guest_id = (vm.config.guestId or "").lower()
        return "windows" in guest_id

    def _extract_vm_data(self, vm) -> dict[str, Any] | None:
        if vm.config is None:
            return None
        if vm.config.template:
            return None
        if vm.name.startswith(_VCLS_PREFIX):
            return None
        if self._is_windows(vm):
            return None
        if not self._is_linux(vm):
            return None

        hostname = fqdn = ip_address = ""
        try:
            if vm.guest:
                raw_host = vm.guest.hostName or ""
                if "." in raw_host:
                    fqdn     = raw_host
                    hostname = raw_host.split(".")[0]
                else:
                    hostname = raw_host
                ip_address = vm.guest.ipAddress or ""
        except Exception:
            pass
        hostname = hostname or vm.name

        os_name = ""
        try:
            os_name = vm.config.guestFullName or (
                vm.guest.guestFullName if vm.guest else ""
            ) or ""
        except Exception:
            pass

        cpu_count = 0
        ram_gb    = 0.0
        try:
            cpu_count = vm.config.hardware.numCPU or 0
            ram_gb    = round((vm.config.hardware.memoryMB or 0) / 1024, 1)
        except Exception:
            pass

        power_state = "unknown"
        try:
            power_state = str(vm.runtime.powerState)
        except Exception:
            pass

        vm_uuid = bios_uuid = ""
        try:
            vm_uuid   = vm.config.uuid or ""
            bios_uuid = vm.config.locationId or ""
        except Exception:
            pass

        tools_status = tools_version = ""
        try:
            if vm.guest:
                tools_status  = str(vm.guest.toolsVersionStatus2 or vm.guest.toolsStatus or "")
                tools_version = vm.guest.toolsVersion or ""
        except Exception:
            pass

        mac_address = network_name = ""
        try:
            if vm.guest and vm.guest.net:
                for nic in vm.guest.net:
                    mac_address  = nic.macAddress or ""
                    network_name = nic.network or ""
                    break
        except Exception:
            pass

        datacenter = cluster = esxi_host = datastore = folder = ""
        try:
            host_ref = vm.runtime.host
            if host_ref:
                esxi_host = host_ref.name or ""
                compute   = host_ref.parent
                if compute:
                    cluster = compute.name or ""
        except Exception:
            pass
        try:
            if vm.datastore:
                datastore = vm.datastore[0].name or ""
        except Exception:
            pass
        try:
            from pyVmomi import vim  # type: ignore
            parent = vm.parent
            parts: list[str] = []
            while parent:
                if isinstance(parent, vim.Datacenter):
                    datacenter = parent.name or ""
                    break
                parts.append(getattr(parent, "name", "") or "")
                parent = getattr(parent, "parent", None)
            folder = "/".join(p for p in reversed(parts) if p)
        except Exception:
            pass

        return {
            "hostname":         hostname,
            "fqdn":             fqdn,
            "ip_address":       ip_address or "0.0.0.0",
            "operating_system": os_name,
            "kernel_version":   "",
            "cpu_count":        cpu_count,
            "ram_gb":           ram_gb,
            "power_state":      power_state,
            "vm_uuid":          vm_uuid,
            "bios_uuid":        bios_uuid,
            "vm_name":          vm.name,
            "tools_status":     tools_status,
            "tools_version":    tools_version,
            "mac_address":      mac_address,
            "network_name":     network_name,
            "datacenter":       datacenter,
            "cluster":          cluster,
            "esxi_host":        esxi_host,
            "datastore":        datastore,
            "folder":           folder,
        }

    # ── Upsert (O(1) dict lookups) ────────────────────────────────────────── #

    def _upsert_server(
        self,
        db,
        vm_data: dict,
        cfg,                    # VmwareConnection or None
        by_uuid:     dict,
        by_bios:     dict,
        by_hostname: dict,
        meta_by_sid: dict,
        connection_id: int | None = None,
        vcenter_name: str = "",
    ) -> str:
        from ..models.server import Server
        from ..models.vmware_server_meta import VmwareServerMeta

        vm_uuid   = vm_data["vm_uuid"]
        bios_uuid = vm_data["bios_uuid"]
        hostname  = vm_data["hostname"]

        if not hostname:
            return "skipped"

        # ── Deduplicate: UUID → BIOS UUID → Hostname ──────────────────────── #
        server: Server | None = None
        if vm_uuid:
            server = by_uuid.get(vm_uuid)
        if server is None and bios_uuid:
            server = by_bios.get(bios_uuid)
        if server is None:
            server = by_hostname.get(hostname)

        # ── Cross-vCenter duplicate detection ────────────────────────────── #
        # If we found a server that already has meta from a DIFFERENT connection,
        # log a duplicate warning but still update metadata (last-write-wins).
        if server is not None and connection_id is not None:
            existing_meta = meta_by_sid.get(server.id)
            if (
                existing_meta
                and existing_meta.connection_id is not None
                and existing_meta.connection_id != connection_id
            ):
                # Duplicate across vCenters — update meta but signal caller
                _update_meta(
                    db, existing_meta, vm_data, connection_id, vcenter_name,
                    self.vcenter_host,
                )
                return "duplicate"

        if server is None:
            server = Server(
                hostname       = hostname,
                ip_address     = vm_data["ip_address"],
                source         = "vmware",
                vmware_vm_uuid = vm_uuid or None,
            )
            db.session.add(server)
            db.session.flush()

            if vm_uuid:
                by_uuid[vm_uuid] = server
            if bios_uuid:
                by_bios[bios_uuid] = server
            by_hostname[hostname] = server
            action = "imported"
        else:
            action = "updated"
            if vm_uuid and not server.vmware_vm_uuid:
                server.vmware_vm_uuid = vm_uuid
                by_uuid[vm_uuid] = server

        # ── Update core inventory fields (vmware-sourced servers only) ──── #
        if server.source in (None, "vmware"):
            server.source = "vmware"
            ip = vm_data["ip_address"]
            if ip and ip != "0.0.0.0":
                server.ip_address = ip
            server.fqdn = vm_data["fqdn"] or server.fqdn
            if vm_data["operating_system"]:
                server.operating_system = vm_data["operating_system"]
            if vm_data["cpu_count"]:
                server.cpu_count = vm_data["cpu_count"]
            if vm_data["ram_gb"]:
                server.ram_gb = vm_data["ram_gb"]

        # Apply defaults only if not already set
        if cfg:
            if getattr(cfg, "location_id", None) and not server.location_id:
                server.location_id = cfg.location_id
            elif getattr(cfg, "default_location_id", None) and not server.location_id:
                server.location_id = cfg.default_location_id
            env_attr = (
                "default_environment_id"
                if hasattr(cfg, "default_environment_id")
                else None
            )
            if env_attr and getattr(cfg, env_attr) and not server.environment_id:
                server.environment_id = getattr(cfg, env_attr)

        db.session.flush()

        # ── Upsert VMware metadata ──────────────────────────────────────── #
        meta = meta_by_sid.get(server.id)
        if meta is None:
            meta = VmwareServerMeta(server_id=server.id)
            db.session.add(meta)
            meta_by_sid[server.id] = meta

        _update_meta(db, meta, vm_data, connection_id, vcenter_name, self.vcenter_host)
        return action


def _update_meta(db, meta, vm_data, connection_id, vcenter_name, vcenter_host):
    """Write all VMware metadata fields to a VmwareServerMeta row."""
    meta.connection_id  = connection_id
    meta.vcenter_name   = vcenter_name
    meta.vcenter_host   = vcenter_host
    meta.datacenter     = vm_data["datacenter"]
    meta.cluster        = vm_data["cluster"]
    meta.esxi_host      = vm_data["esxi_host"]
    meta.datastore      = vm_data["datastore"]
    meta.folder         = vm_data["folder"]
    meta.power_state    = vm_data["power_state"]
    meta.vm_uuid        = vm_data["vm_uuid"]
    meta.bios_uuid      = vm_data["bios_uuid"]
    meta.vm_name        = vm_data["vm_name"]
    meta.tools_status   = vm_data["tools_status"]
    meta.tools_version  = vm_data["tools_version"]
    meta.mac_address    = vm_data["mac_address"]
    meta.network_name   = vm_data["network_name"]
    meta.last_synced_at = datetime.now(timezone.utc)


def _server_belongs_to_conn(server, connection_id: int) -> bool:
    """Check if a server's meta record belongs to a given connection."""
    from sqlalchemy import text
    from ..extensions import db
    row = db.session.execute(
        text("SELECT connection_id FROM vmware_server_meta WHERE server_id = :sid LIMIT 1"),
        {"sid": server.id},
    ).fetchone()
    return row is not None and row[0] == connection_id


# ── Module-level convenience: sync a single connection ───────────────────── #

def sync_connection(app, connection_id: int, triggered_by: str = "scheduled") -> None:
    """
    Sync a single VmwareConnection by ID.
    Intended to be called from APScheduler or route handlers.
    """
    with app.app_context():
        from ..models.vmware_connection import VmwareConnection
        conn = VmwareConnection.query.get(connection_id)
        if conn is None or not conn.enabled:
            return
        if is_sync_running(connection_id):
            logger.info("Scheduled sync skipped — already running (conn_id=%d)", connection_id)
            return
        svc = VmwareService.from_connection(conn)
        svc.sync_now(app, triggered_by=triggered_by)


def sync_all_connections(app, triggered_by: str = "manual") -> tuple[int, int]:
    """
    Loop through all enabled VmwareConnections and sync each one sequentially.
    A failure on one connection does NOT stop the rest.
    Returns (started_count, skipped_count).
    """
    started = skipped = 0

    with app.app_context():
        from ..models.vmware_connection import VmwareConnection
        connections = VmwareConnection.query.filter_by(enabled=True).all()

    for conn in connections:
        try:
            if is_sync_running(conn.id):
                logger.info(
                    "sync_all: skipping %s — already running", conn.name
                )
                skipped += 1
                continue
            svc = VmwareService.from_connection(conn)
            ok, _ = svc.sync_now(app, triggered_by=triggered_by)
            if ok:
                started += 1
            else:
                skipped += 1
        except Exception as exc:
            logger.error("sync_all: error starting %s: %s", conn.name, exc)
            skipped += 1

    return started, skipped
