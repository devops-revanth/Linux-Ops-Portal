"""
VMware vSphere service — Linux VM discovery and inventory synchronisation.

Responsibilities:
  • Connect to vCenter using pyVmomi (SmartConnect)
  • Test the connection and return a friendly status string
  • Walk the VM inventory and collect all Linux VMs
  • Upsert Server + VmwareServerMeta records without duplicating entries
  • Log every sync run in VmwareSyncLog
  • Run the sync in a background thread so routes return immediately
"""
from __future__ import annotations

import logging
import ssl
import threading
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Global lock — prevents two concurrent syncs
_sync_lock = threading.Lock()

# Keywords in VMware guestId that indicate a Linux guest
_LINUX_GUEST_KEYWORDS = (
    "rhel", "centos", "fedora", "ubuntu", "debian", "sles",
    "opensuse", "oracle", "rocky", "alma", "amazon", "asianux",
    "mandrake", "redhat", "other24xlinux", "other26xlinux",
    "other3xlinux", "otherlinux", "linux",
)

# vCLS management VMs — always skip
_VCLS_PREFIX = "vCLS"


class VmwareConnectionError(Exception):
    """Raised when a vCenter connection or authentication attempt fails."""


class VmwareService:
    """High-level interface to the VMware vSphere API for LOP."""

    def __init__(self, vcenter_host: str, port: int, username: str,
                 password: str, ignore_ssl: bool = False):
        self.vcenter_host = vcenter_host
        self.port = port
        self.username = username
        self.password = password
        self.ignore_ssl = ignore_ssl

    @classmethod
    def from_config(cls, cfg) -> "VmwareService":
        """Build a VmwareService from a VmwareConfig instance."""
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
        """Return a connected pyVmomi ServiceInstance."""
        try:
            from pyVim.connect import SmartConnect  # type: ignore
        except ImportError:
            raise VmwareConnectionError(
                "pyVmomi is not installed. Run: pip install pyVmomi"
            )
        ctx = self._ssl_context()
        try:
            si = SmartConnect(
                host=self.vcenter_host,
                user=self.username,
                pwd=self.password,
                port=self.port,
                sslContext=ctx,
                connectionPoolTimeout=30,
            )
            return si
        except Exception as exc:
            msg = str(exc).lower()
            if "incorrect user name" in msg or "authentication" in msg or "login" in msg:
                raise VmwareConnectionError(f"Authentication Failed: {exc}")
            if "ssl" in msg or "certificate" in msg or "handshake" in msg:
                raise VmwareConnectionError(f"SSL Error: {exc}")
            if "timeout" in msg or "timed out" in msg:
                raise VmwareConnectionError(f"Connection Timeout: {exc}")
            raise VmwareConnectionError(f"Disconnected: {exc}")

    def test_connection(self) -> tuple[bool, str, str]:
        """
        Test vCenter connectivity.

        Returns:
            (success, message, status_string)
            status_string matches CONNECTION_STATUS_OPTIONS in vmware_config.py
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
            status = str(exc).split(":")[0].strip()
            if status not in ("Authentication Failed", "SSL Error", "Connection Timeout"):
                status = "Disconnected"
            return False, str(exc), status
        except Exception as exc:
            return False, f"Disconnected: {exc}", "Disconnected"
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
        If a sync is already running, returns (False, reason).
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
        """Background sync worker — runs inside a fresh app context."""
        with app.app_context():
            from ..extensions import db
            from ..models.vmware_config import VmwareConfig, VmwareSyncLog
            from ..audit import commit_audit

            # ── Create running log entry ──────────────────────────────────── #
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
            imported = updated = skipped = 0

            try:
                commit_audit("vmware.sync.started", details=f"triggered_by={triggered_by}")

                si = self._connect()
                vms = self._collect_linux_vms(si)
                logger.info("VMware: discovered %d Linux VMs", len(vms))

                for vm_data in vms:
                    try:
                        res = self._upsert_server(db, vm_data, cfg)
                        if res == "imported":
                            imported += 1
                            commit_audit(
                                "vmware.vm.imported",
                                target=vm_data.get("hostname", ""),
                            )
                        elif res == "updated":
                            updated += 1
                            commit_audit(
                                "vmware.vm.updated",
                                target=vm_data.get("hostname", ""),
                            )
                        else:
                            skipped += 1
                    except Exception as exc:
                        logger.warning(
                            "VMware: failed to upsert %s: %s",
                            vm_data.get("vm_name"), exc,
                        )
                        db.session.rollback()
                        skipped += 1

                db.session.commit()
                duration = time.monotonic() - t0

                # Update log
                log = VmwareSyncLog.query.get(log_id)
                log.status = "completed"
                log.finished_at = datetime.now(timezone.utc)
                log.vms_imported = imported
                log.vms_updated = updated
                log.vms_skipped = skipped

                # Update config stats
                cfg.last_sync_at = datetime.now(timezone.utc)
                cfg.last_sync_ok_at = datetime.now(timezone.utc)
                cfg.last_sync_vms = imported + updated
                cfg.last_sync_duration_s = round(duration, 2)
                db.session.commit()

                commit_audit(
                    "vmware.sync.completed",
                    details=(
                        f"imported={imported} updated={updated} "
                        f"skipped={skipped} duration={duration:.1f}s"
                    ),
                )
                logger.info(
                    "VMware sync done: %d imported, %d updated, %d skipped (%.1fs)",
                    imported, updated, skipped, duration,
                )

            except Exception as exc:
                duration = time.monotonic() - t0
                logger.error("VMware sync failed: %s", exc, exc_info=True)
                try:
                    db.session.rollback()
                    log = VmwareSyncLog.query.get(log_id)
                    log.status = "failed"
                    log.finished_at = datetime.now(timezone.utc)
                    log.vms_imported = imported
                    log.vms_updated = updated
                    log.vms_skipped = skipped
                    log.error_message = str(exc)[:1000]

                    cfg.last_sync_at = datetime.now(timezone.utc)
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
        if vm.config is None:
            return False
        if vm.config.template:
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
        """Extract fields from a pyVmomi VirtualMachine object.
        Returns None for templates, vCLS VMs, and Windows guests."""
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
        hostname = hostname or vm.name

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

        # ── UUIDs ────────────────────────────────────────────────────────── #
        vm_uuid = bios_uuid = ""
        try:
            vm_uuid = vm.config.uuid or ""
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
                    mac_address = nic.macAddress or ""
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
            "hostname":     hostname,
            "fqdn":         fqdn,
            "ip_address":   ip_address or "0.0.0.0",
            "operating_system": os_name,
            "kernel_version":   kernel,
            "cpu_count":    cpu_count,
            "ram_gb":       ram_gb,
            "power_state":  power_state,
            "vm_uuid":      vm_uuid,
            "bios_uuid":    bios_uuid,
            "vm_name":      vm.name,
            "tools_status": tools_status,
            "tools_version": tools_version,
            "mac_address":  mac_address,
            "network_name": network_name,
            "datacenter":   datacenter,
            "cluster":      cluster,
            "esxi_host":    esxi_host,
            "datastore":    datastore,
            "folder":       folder,
        }

    # ── Upsert ────────────────────────────────────────────────────────────── #

    def _upsert_server(self, db, vm_data: dict, cfg) -> str:
        """
        Create or update a Server + VmwareServerMeta from discovered VM data.

        Match priority:
          1. vmware_vm_uuid — most reliable
          2. hostname       — fallback

        Policy:
          • New servers are created with source="vmware".
          • Manually-added servers (source="manual"): only VMware metadata is
            updated; core inventory fields (hostname, IP, OS…) are NOT
            overwritten.
          • Existing vmware servers are fully updated.

        Returns: "imported" | "updated" | "skipped"
        """
        from ..models.server import Server
        from ..models.vmware_server_meta import VmwareServerMeta

        vm_uuid = vm_data["vm_uuid"]
        hostname = vm_data["hostname"]

        if not hostname or hostname == "0.0.0.0":
            return "skipped"

        # ── Find existing record ───────────────────────────────────────────── #
        server: Server | None = None
        if vm_uuid:
            server = Server.query.filter_by(vmware_vm_uuid=vm_uuid).first()
        if server is None and hostname:
            server = Server.query.filter_by(hostname=hostname).first()

        if server is None:
            # New server — create it
            server = Server(
                hostname=hostname,
                ip_address=vm_data["ip_address"],
                source="vmware",
                vmware_vm_uuid=vm_uuid or None,
            )
            db.session.add(server)
            db.session.flush()
            action = "imported"
        else:
            action = "updated"
            # Tag with UUID if we found by hostname
            if vm_uuid and not server.vmware_vm_uuid:
                server.vmware_vm_uuid = vm_uuid

        # ── Update core fields (only for vmware-sourced servers) ───────────── #
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

        # Apply defaults only if not already assigned
        if cfg.default_location_id and not server.location_id:
            server.location_id = cfg.default_location_id
        if cfg.default_environment_id and not server.environment_id:
            server.environment_id = cfg.default_environment_id

        db.session.flush()

        # ── Upsert VMware metadata ─────────────────────────────────────────── #
        meta = VmwareServerMeta.query.filter_by(server_id=server.id).first()
        if meta is None:
            meta = VmwareServerMeta(server_id=server.id)
            db.session.add(meta)

        meta.vcenter_host  = self.vcenter_host
        meta.datacenter    = vm_data["datacenter"]
        meta.cluster       = vm_data["cluster"]
        meta.esxi_host     = vm_data["esxi_host"]
        meta.datastore     = vm_data["datastore"]
        meta.folder        = vm_data["folder"]
        meta.power_state   = vm_data["power_state"]
        meta.vm_uuid       = vm_uuid
        meta.bios_uuid     = vm_data["bios_uuid"]
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
