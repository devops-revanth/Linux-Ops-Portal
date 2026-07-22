"""
VMware vSphere service — Linux VM discovery and inventory synchronisation.

Responsibilities:
  • Connect to vCenter using pyVmomi (SmartConnect)
  • Test the connection and return a friendly status string
  • Walk the VM inventory and collect all Linux VMs
  • Upsert Server + VmwareServerMeta without duplicating entries
  • Log every sync run in VmwareSyncLog
  • Mark servers that disappeared from vCenter as inactive
  • Run the sync in a background thread so routes return immediately

Performance design:
  • Pre-loads ALL existing servers and meta records in 3 queries before the
    upsert loop — O(1) dict lookups per VM instead of per-VM DB queries.
  • Accumulates all upserts in one transaction; commits once at the end.
  • Per-VM audit entries use log_action (no-commit) and are flushed with the
    batch commit rather than generating one DB round-trip per VM.

Deduplication priority:
  1. vmware_vm_uuid  (vm.config.uuid)    — most stable
  2. bios_uuid       (vm.config.locationId) — fallback if UUID mismatch
  3. hostname                               — last resort
"""
from __future__ import annotations

import logging
import ssl
import threading
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Global lock — prevents concurrent syncs from the same process
_sync_lock = threading.Lock()

# Keywords in VMware guestId that indicate a Linux guest
_LINUX_GUEST_KEYWORDS = (
    "rhel", "centos", "fedora", "ubuntu", "debian", "sles",
    "opensuse", "oracle", "rocky", "alma", "amazon", "asianux",
    "mandrake", "redhat", "other24xlinux", "other26xlinux",
    "other3xlinux", "otherlinux", "linux",
)

# vCLS management VMs are always skipped
_VCLS_PREFIX = "vCLS"


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
    ):
        self.vcenter_host = vcenter_host
        self.port = port
        self.username = username
        self.password = password
        self.ignore_ssl = ignore_ssl

    @classmethod
    def from_config(cls, cfg) -> "VmwareService":
        """Build a VmwareService from a VmwareConfig model instance."""
        return cls(
            vcenter_host=cfg.vcenter_host or "",
            port=cfg.port or 443,
            username=cfg.username or "",
            password=cfg.get_password() or "",
            ignore_ssl=cfg.ignore_ssl,
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
        """
        Return a connected pyVmomi ServiceInstance.

        Raises VmwareConnectionError with a sanitised message — never exposes
        raw credentials or internal exception details to callers.
        """
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
            # Classify without leaking credentials or internal details
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
        """
        Test vCenter connectivity.

        Returns:
            (success: bool, message: str, status_string: str)
            status_string matches CONNECTION_STATUS_OPTIONS in vmware_config.py.
        """
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
            # Extract the status prefix (e.g. "Authentication Failed")
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

    # ── Sync orchestration ────────────────────────────────────────────────── #

    def sync_now(self, app, triggered_by: str = "manual") -> tuple[bool, str]:
        """
        Trigger a background sync.  Returns (started, message).
        Returns (False, reason) if a sync is already running.
        """
        if not _sync_lock.acquire(blocking=False):
            return False, "A sync is already in progress."
        thread = threading.Thread(
            target=self._do_sync,
            args=(app, triggered_by),
            daemon=True,
            name="vmware-sync",
        )
        thread.start()
        return True, "Sync started."

    def _do_sync(self, app, triggered_by: str) -> None:
        """
        Background sync worker.  Runs inside a fresh Flask app context.

        Phases:
          1. Create a VmwareSyncLog row with status='running'.
          2. Connect to vCenter and collect all Linux VMs.
          3. Pre-load existing Server + VmwareServerMeta into memory dicts.
          4. Upsert each discovered VM (O(1) dict lookups, one transaction).
          5. Mark any VMware-sourced server not seen in this sync as inactive.
          6. Commit everything in a single batch.
          7. Update sync stats on VmwareConfig.
        """
        with app.app_context():
            from ..extensions import db
            from ..models.vmware_config import VmwareConfig, VmwareSyncLog
            from ..models.server import Server
            from ..models.vmware_server_meta import VmwareServerMeta
            from ..audit import log_action, commit_audit

            # ── Create sync log (running) ─────────────────────────────────── #
            log = VmwareSyncLog(
                status="running",
                started_at=datetime.now(timezone.utc),
                triggered_by=triggered_by,
            )
            db.session.add(log)
            db.session.commit()
            log_id = log.id

            cfg = VmwareConfig.get()
            t0 = time.monotonic()
            si = None
            imported = updated = skipped = stale_marked = 0

            try:
                log_action("vmware.sync.started", details=f"triggered_by={triggered_by}")
                db.session.commit()

                si = self._connect()
                vms = self._collect_linux_vms(si)
                logger.info("VMware: discovered %d Linux VMs", len(vms))

                # ── Pre-load all existing servers (3 queries) ─────────────── #
                all_servers: list[Server] = Server.query.all()
                vmware_servers: list[Server] = [s for s in all_servers if s.source == "vmware"]
                all_meta: list[VmwareServerMeta] = VmwareServerMeta.query.all()

                # O(1) lookup dicts
                by_uuid:     dict[str, Server]          = {}
                by_bios:     dict[str, Server]          = {}
                by_hostname: dict[str, Server]          = {}
                meta_by_sid: dict[int, VmwareServerMeta] = {}

                for s in all_servers:
                    by_hostname[s.hostname] = s
                    if s.vmware_vm_uuid:
                        by_uuid[s.vmware_vm_uuid] = s

                for m in all_meta:
                    meta_by_sid[m.server_id] = m
                    if m.bios_uuid:
                        # Map BIOS UUID → the owning server
                        server_for_bios = next(
                            (s for s in all_servers if s.id == m.server_id), None
                        )
                        if server_for_bios:
                            by_bios[m.bios_uuid] = server_for_bios

                # ── Track UUIDs seen in this sync (for stale detection) ───── #
                synced_vm_uuids: set[str] = set()

                # ── Upsert each discovered VM ─────────────────────────────── #
                for vm_data in vms:
                    try:
                        res = self._upsert_server(
                            db, vm_data, cfg,
                            by_uuid, by_bios, by_hostname, meta_by_sid,
                        )
                        if vm_data["vm_uuid"]:
                            synced_vm_uuids.add(vm_data["vm_uuid"])

                        if res == "imported":
                            imported += 1
                            log_action(
                                "vmware.vm.imported",
                                target=vm_data.get("hostname", ""),
                                details=f"vm={vm_data.get('vm_name', '')}",
                            )
                        elif res == "updated":
                            updated += 1
                        else:
                            skipped += 1
                    except Exception as exc:
                        logger.warning(
                            "VMware: failed to upsert %s: %s",
                            vm_data.get("vm_name"), exc,
                        )
                        db.session.rollback()
                        skipped += 1

                # ── Mark stale VMware servers inactive ────────────────────── #
                #
                # A server is stale if it was previously imported from VMware
                # (source='vmware', has a vmware_vm_uuid) but its UUID was NOT
                # seen in this sync.  We mark it inactive — never delete it —
                # to preserve historical patching and audit data.
                for srv in vmware_servers:
                    if not srv.vmware_vm_uuid:
                        continue  # no UUID → can't reliably detect staleness
                    if srv.vmware_vm_uuid in synced_vm_uuids:
                        continue  # seen in this sync — healthy
                    if srv.status == "active":
                        srv.status = "inactive"
                        log_action(
                            "vmware.vm.stale",
                            target=srv.hostname,
                            details=(
                                "VM no longer present in vCenter — "
                                "marked inactive (historical data preserved)"
                            ),
                        )
                        stale_marked += 1

                # ── Single batch commit ───────────────────────────────────── #
                db.session.commit()
                duration = time.monotonic() - t0

                # Update sync log
                log = VmwareSyncLog.query.get(log_id)
                log.status        = "completed"
                log.finished_at   = datetime.now(timezone.utc)
                log.vms_imported  = imported
                log.vms_updated   = updated
                log.vms_skipped   = skipped

                cfg.last_sync_at       = datetime.now(timezone.utc)
                cfg.last_sync_ok_at    = datetime.now(timezone.utc)
                cfg.last_sync_vms      = imported + updated
                cfg.last_sync_duration_s = round(duration, 2)
                db.session.commit()

                commit_audit(
                    "vmware.sync.completed",
                    details=(
                        f"imported={imported} updated={updated} "
                        f"skipped={skipped} stale_marked={stale_marked} "
                        f"duration={duration:.1f}s"
                    ),
                )
                logger.info(
                    "VMware sync done: %d imported, %d updated, "
                    "%d skipped, %d stale marked (%.1fs)",
                    imported, updated, skipped, stale_marked, duration,
                )

            except Exception as exc:
                duration = time.monotonic() - t0
                logger.error("VMware sync failed: %s", exc, exc_info=True)
                try:
                    db.session.rollback()
                    log = VmwareSyncLog.query.get(log_id)
                    log.status        = "failed"
                    log.finished_at   = datetime.now(timezone.utc)
                    log.vms_imported  = imported
                    log.vms_updated   = updated
                    log.vms_skipped   = skipped
                    log.error_message = str(exc)[:1000]

                    cfg.last_sync_at      = datetime.now(timezone.utc)
                    cfg.last_sync_fail_at = datetime.now(timezone.utc)
                    db.session.commit()

                    commit_audit("vmware.sync.failed", details=str(exc)[:500])
                except Exception:
                    logger.exception("VMware: failed to update sync log after failure")
            finally:
                if si:
                    try:
                        from pyVim.connect import Disconnect  # type: ignore
                        Disconnect(si)
                    except Exception:
                        pass
                _sync_lock.release()

    # ── VM discovery ──────────────────────────────────────────────────────── #

    def _collect_linux_vms(self, si) -> list[dict[str, Any]]:
        """Walk the vCenter container view and return Linux VM data dicts."""
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
                    logger.debug("VMware: skipping VM due to error: %s", exc)
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
        """
        Extract inventory fields from a pyVmomi VirtualMachine object.

        Returns None for templates, vCLS VMs, Windows guests, and VMs with
        an unknown or unclassified OS to keep the inventory Linux-only.
        """
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

        # ── Identity ──────────────────────────────────────────────────────── #
        hostname = fqdn = ip_address = ""
        try:
            if vm.guest:
                raw_host = vm.guest.hostName or ""
                if "." in raw_host:
                    fqdn = raw_host
                    hostname = raw_host.split(".")[0]
                else:
                    hostname = raw_host
                ip_address = vm.guest.ipAddress or ""
        except Exception:
            pass
        hostname = hostname or vm.name  # fall back to VM display name

        # ── OS info ───────────────────────────────────────────────────────── #
        os_name = kernel = ""
        try:
            os_name = vm.config.guestFullName or (
                vm.guest.guestFullName if vm.guest else ""
            ) or ""
        except Exception:
            pass

        # ── Hardware ──────────────────────────────────────────────────────── #
        cpu_count = 0
        ram_gb = 0.0
        try:
            cpu_count = vm.config.hardware.numCPU or 0
            ram_gb = round((vm.config.hardware.memoryMB or 0) / 1024, 1)
        except Exception:
            pass

        # ── Runtime ───────────────────────────────────────────────────────── #
        power_state = "unknown"
        try:
            power_state = str(vm.runtime.powerState)
        except Exception:
            pass

        # ── UUIDs ─────────────────────────────────────────────────────────── #
        vm_uuid = bios_uuid = ""
        try:
            vm_uuid   = vm.config.uuid or ""
            bios_uuid = vm.config.locationId or ""
        except Exception:
            pass

        # ── VMware Tools ──────────────────────────────────────────────────── #
        tools_status = tools_version = ""
        try:
            if vm.guest:
                tools_status = str(
                    vm.guest.toolsVersionStatus2 or vm.guest.toolsStatus or ""
                )
                tools_version = vm.guest.toolsVersion or ""
        except Exception:
            pass

        # ── Network (first NIC) ───────────────────────────────────────────── #
        mac_address = network_name = ""
        try:
            if vm.guest and vm.guest.net:
                for nic in vm.guest.net:
                    mac_address  = nic.macAddress or ""
                    network_name = nic.network or ""
                    break
        except Exception:
            pass

        # ── Infrastructure ────────────────────────────────────────────────── #
        datacenter = cluster = esxi_host = datastore = folder = ""
        try:
            host_ref = vm.runtime.host
            if host_ref:
                esxi_host = host_ref.name or ""
                compute = host_ref.parent
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
            "kernel_version":   kernel,
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

    # ── Upsert (uses pre-loaded dicts — O(1) per VM) ──────────────────────── #

    def _upsert_server(
        self,
        db,
        vm_data: dict,
        cfg,
        by_uuid:     dict,
        by_bios:     dict,
        by_hostname: dict,
        meta_by_sid: dict,
    ) -> str:
        """
        Create or update a Server + VmwareServerMeta for one discovered VM.

        Uses pre-loaded in-memory dicts for O(1) deduplication lookups:
          1. vmware_vm_uuid
          2. bios_uuid  (vm.config.locationId)
          3. hostname   (last resort)

        Policy:
          • New servers → source="vmware".
          • Manually-added servers (source="manual") → only VMware metadata
            is written; hostname / IP / OS fields are NOT overwritten.
          • Existing vmware servers → fully updated.

        Returns: "imported" | "updated" | "skipped"
        """
        from ..models.server import Server
        from ..models.vmware_server_meta import VmwareServerMeta

        vm_uuid   = vm_data["vm_uuid"]
        bios_uuid = vm_data["bios_uuid"]
        hostname  = vm_data["hostname"]

        if not hostname:
            return "skipped"

        # ── Deduplicate: UUID → BIOS UUID → Hostname ─────────────────────── #
        server: Server | None = None
        if vm_uuid:
            server = by_uuid.get(vm_uuid)
        if server is None and bios_uuid:
            server = by_bios.get(bios_uuid)
        if server is None:
            server = by_hostname.get(hostname)

        if server is None:
            # ── New server ──────────────────────────────────────────────── #
            server = Server(
                hostname       = hostname,
                ip_address     = vm_data["ip_address"],
                source         = "vmware",
                vmware_vm_uuid = vm_uuid or None,
            )
            db.session.add(server)
            db.session.flush()   # populate server.id

            # Update in-memory lookups so subsequent VMs don't create dupes
            if vm_uuid:
                by_uuid[vm_uuid] = server
            if bios_uuid:
                by_bios[bios_uuid] = server
            by_hostname[hostname] = server
            action = "imported"
        else:
            action = "updated"
            # Backfill UUID if we matched only by BIOS UUID or hostname
            if vm_uuid and not server.vmware_vm_uuid:
                server.vmware_vm_uuid = vm_uuid
                by_uuid[vm_uuid] = server

        # ── Update core inventory fields (vmware-sourced servers only) ────── #
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
            if vm_data["kernel_version"]:
                server.kernel_version = vm_data["kernel_version"]

        # Apply default location / environment only if not already set
        if cfg.default_location_id and not server.location_id:
            server.location_id = cfg.default_location_id
        if cfg.default_environment_id and not server.environment_id:
            server.environment_id = cfg.default_environment_id

        db.session.flush()   # ensure server.id is available for meta

        # ── Upsert VMware metadata ──────────────────────────────────────── #
        meta = meta_by_sid.get(server.id)
        if meta is None:
            meta = VmwareServerMeta(server_id=server.id)
            db.session.add(meta)
            meta_by_sid[server.id] = meta

        meta.vcenter_host  = self.vcenter_host
        meta.datacenter    = vm_data["datacenter"]
        meta.cluster       = vm_data["cluster"]
        meta.esxi_host     = vm_data["esxi_host"]
        meta.datastore     = vm_data["datastore"]
        meta.folder        = vm_data["folder"]
        meta.power_state   = vm_data["power_state"]
        meta.vm_uuid       = vm_uuid
        meta.bios_uuid     = bios_uuid
        meta.vm_name       = vm_data["vm_name"]
        meta.tools_status  = vm_data["tools_status"]
        meta.tools_version = vm_data["tools_version"]
        meta.mac_address   = vm_data["mac_address"]
        meta.network_name  = vm_data["network_name"]
        meta.last_synced_at = datetime.now(timezone.utc)

        return action


def is_sync_running() -> bool:
    """Return True if a VMware sync background thread is active."""
    return _sync_lock.locked()
