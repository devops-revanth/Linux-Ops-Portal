"""
Ansible fact collection models.

AnsibleFilesystem    — filesystem / mount data per server (from ansible_mounts)
AnsibleServerService — service states for a curated list of important services
AnsibleRepository    — enabled yum/dnf repos per server
AnsibleSyncJob       — audit trail for each fact collection run
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..extensions import db

# ── Important services to track ──────────────────────────────────────────────
# LOP only stores status for these services; all others are ignored.
TRACKED_SERVICES: list[str] = [
    "sshd",
    "sshd.service",
    "chronyd",
    "chronyd.service",
    "ntpd",
    "ntpd.service",
    "firewalld",
    "firewalld.service",
    "NetworkManager",
    "NetworkManager.service",
    "docker",
    "docker.service",
    "podman",
    "podman.service",
    "crond",
    "crond.service",
    "cron",
    "cron.service",
    "auditd",
    "auditd.service",
    "rsyslog",
    "rsyslog.service",
    "tuned",
    "tuned.service",
    "irqbalance",
    "irqbalance.service",
]

# Canonical name map: strip ".service" suffix for display
def _canonical_service(name: str) -> str:
    return name.removesuffix(".service")


SYNC_STATUS_CHOICES: list[str] = [
    "running",
    "completed",
    "failed",
    "partial",
]


class AnsibleFilesystem(db.Model):
    """
    Filesystem mount point collected from a server via ansible_mounts.
    Records are replaced on every successful sync for that server.
    """
    __tablename__ = "ansible_filesystems"

    id: int = db.Column(db.Integer, primary_key=True)
    server_id: int = db.Column(
        db.Integer,
        db.ForeignKey("linux_servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mount: str   = db.Column(db.String(255), nullable=False)  # e.g. /
    device: str  = db.Column(db.String(255), nullable=True)   # e.g. /dev/sda1
    fstype: str  = db.Column(db.String(50),  nullable=True)   # e.g. xfs
    size_gb: float  = db.Column(db.Float, nullable=True)
    used_gb: float  = db.Column(db.Float, nullable=True)
    avail_gb: float = db.Column(db.Float, nullable=True)
    use_pct: int    = db.Column(db.Integer, nullable=True)    # 0-100
    synced_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<AnsibleFilesystem server={self.server_id} mount={self.mount!r}>"


class AnsibleServerService(db.Model):
    """
    State of a tracked service on a server, collected via ansible service_facts.
    Only services in TRACKED_SERVICES are stored.
    Records are replaced on every successful sync for that server.
    """
    __tablename__ = "ansible_server_services"

    id: int = db.Column(db.Integer, primary_key=True)
    server_id: int = db.Column(
        db.Integer,
        db.ForeignKey("linux_servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: str    = db.Column(db.String(100), nullable=False)  # canonical (no .service)
    state: str   = db.Column(db.String(30),  nullable=True)   # running | stopped | failed
    enabled: str = db.Column(db.String(20),  nullable=True)   # enabled | disabled | static
    synced_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        db.UniqueConstraint("server_id", "name", name="uq_server_service"),
    )

    def __repr__(self) -> str:
        return f"<AnsibleServerService server={self.server_id} {self.name}={self.state}>"


class AnsibleRepository(db.Model):
    """
    Enabled package repositories on a server, collected via `yum repolist`.
    Records are replaced on every successful sync for that server.
    """
    __tablename__ = "ansible_repositories"

    id: int = db.Column(db.Integer, primary_key=True)
    server_id: int = db.Column(
        db.Integer,
        db.ForeignKey("linux_servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    repo_id: str   = db.Column(db.String(200), nullable=False)   # e.g. rhel-9-baseos
    repo_name: str = db.Column(db.String(255), nullable=True)    # human-readable name
    enabled: bool  = db.Column(db.Boolean, nullable=False, default=True)
    baseurl: str   = db.Column(db.Text, nullable=True)
    synced_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        db.UniqueConstraint("server_id", "repo_id", name="uq_server_repo"),
    )

    def __repr__(self) -> str:
        return f"<AnsibleRepository server={self.server_id} repo={self.repo_id!r}>"


class AnsibleSyncJob(db.Model):
    """
    Audit record for a fact collection run.
    One row is created per run (manual or scheduled).
    """
    __tablename__ = "ansible_sync_jobs"

    id: int = db.Column(db.Integer, primary_key=True)
    started_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    triggered_by: str = db.Column(db.String(50), nullable=False, default="manual")
    # "manual" | "scheduled"

    status: str = db.Column(db.String(20), nullable=False, default="running")
    # running | completed | failed | partial

    servers_total:  int = db.Column(db.Integer, nullable=False, default=0)
    servers_ok:     int = db.Column(db.Integer, nullable=False, default=0)
    servers_failed: int = db.Column(db.Integer, nullable=False, default=0)
    packages_synced: int = db.Column(db.Integer, nullable=False, default=0)
    error_message:  str = db.Column(db.Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AnsibleSyncJob id={self.id} status={self.status} "
            f"ok={self.servers_ok}/{self.servers_total}>"
        )
