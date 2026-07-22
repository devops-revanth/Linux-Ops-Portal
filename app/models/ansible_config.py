"""
Ansible integration configuration and inventory host models.

AnsibleConfig        — singleton: connection settings, encrypted credentials,
                       discovered stats (versions, host count, playbook count).
AnsibleInventoryHost — one row per hostname discovered in the Ansible inventory;
                       used to cross-reference LOP servers with Ansible managed hosts.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..extensions import db


AUTH_METHOD_CHOICES: list[tuple[str, str]] = [
    ("key",      "SSH Private Key"),
    ("password", "Username / Password"),
]

INVENTORY_SOURCE_CHOICES: list[tuple[str, str]] = [
    ("static",    "Static Inventory File"),
    ("dynamic",   "Dynamic Inventory"),
    ("directory", "Inventory Directory"),
]

CONNECTION_STATUS_OPTIONS: list[str] = [
    "Not Tested",
    "Connected",
    "Disconnected",
    "Authentication Failed",
    "Host Key Mismatch",
    "Inventory Missing",
    "Playbook Directory Missing",
    "Ansible Not Installed",
    "Connection Timeout",
]


class AnsibleConfig(db.Model):
    __tablename__ = "ansible_config"

    id: int = db.Column(db.Integer, primary_key=True)

    # ── Enable / disable ────────────────────────────────────────────────── #
    enabled: bool = db.Column(db.Boolean, nullable=False, default=False)

    # ── Control node connection ──────────────────────────────────────────── #
    control_node: str = db.Column(db.String(255), nullable=True)
    port: int = db.Column(db.Integer, nullable=False, default=22)
    username: str = db.Column(db.String(100), nullable=True)

    # ── Authentication ───────────────────────────────────────────────────── #
    auth_method: str = db.Column(
        db.String(20), nullable=False, default="key"
    )  # key | password
    ssh_password_enc: str = db.Column(db.Text, nullable=True)
    ssh_private_key_enc: str = db.Column(db.Text, nullable=True)

    # ── Ansible Vault ────────────────────────────────────────────────────── #
    vault_enabled: bool = db.Column(db.Boolean, nullable=False, default=False)
    vault_password_enc: str = db.Column(db.Text, nullable=True)

    # ── Paths ────────────────────────────────────────────────────────────── #
    inventory_source: str = db.Column(
        db.String(20), nullable=False, default="static"
    )  # static | dynamic | directory
    inventory_path: str = db.Column(
        db.Text, nullable=False, default="/etc/ansible/hosts"
    )
    playbook_dir: str = db.Column(
        db.Text, nullable=False, default="/etc/ansible/playbooks"
    )
    collections_dir: str = db.Column(db.Text, nullable=True)

    # ── Connectivity options ─────────────────────────────────────────────── #
    host_key_checking: bool = db.Column(db.Boolean, nullable=False, default=True)
    connection_timeout: int = db.Column(db.Integer, nullable=False, default=30)

    # ── Connection status ────────────────────────────────────────────────── #
    connection_status: str = db.Column(
        db.String(50), nullable=False, default="Not Tested"
    )
    last_test_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)
    last_connected_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)

    # ── Discovered information ───────────────────────────────────────────── #
    ansible_version: str = db.Column(db.String(50), nullable=True)
    python_version: str = db.Column(db.String(50), nullable=True)
    last_inventory_hosts: int = db.Column(db.Integer, nullable=False, default=0)
    last_playbooks_found: int = db.Column(db.Integer, nullable=False, default=0)
    last_validation_at: datetime = db.Column(db.DateTime(timezone=True), nullable=True)

    updated_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Singleton helper ─────────────────────────────────────────────────── #

    @classmethod
    def get(cls) -> "AnsibleConfig":
        """Return (or create with defaults) the singleton config record."""
        cfg = cls.query.first()
        if cfg is None:
            cfg = cls()
            db.session.add(cfg)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                cfg = cls.query.first() or cls()
        return cfg

    # ── Credential helpers ───────────────────────────────────────────────── #

    def set_ssh_password(self, plaintext: str) -> None:
        if not plaintext:
            return
        from ..encryption import encrypt_value
        self.ssh_password_enc = encrypt_value(plaintext)

    def get_ssh_password(self) -> str | None:
        if not self.ssh_password_enc:
            return None
        from ..encryption import decrypt_value
        return decrypt_value(self.ssh_password_enc)

    def set_ssh_private_key(self, plaintext: str) -> None:
        if not plaintext:
            return
        from ..encryption import encrypt_value
        self.ssh_private_key_enc = encrypt_value(plaintext)

    def get_ssh_private_key(self) -> str | None:
        if not self.ssh_private_key_enc:
            return None
        from ..encryption import decrypt_value
        return decrypt_value(self.ssh_private_key_enc)

    def set_vault_password(self, plaintext: str) -> None:
        if not plaintext:
            return
        from ..encryption import encrypt_value
        self.vault_password_enc = encrypt_value(plaintext)

    def get_vault_password(self) -> str | None:
        if not self.vault_password_enc:
            return None
        from ..encryption import decrypt_value
        return decrypt_value(self.vault_password_enc)

    def __repr__(self) -> str:
        return f"<AnsibleConfig node={self.control_node!r} enabled={self.enabled}>"


class AnsibleInventoryHost(db.Model):
    """
    Hosts discovered from the Ansible inventory during the last successful
    Validate Inventory operation.  One row per hostname.  Used to mark
    servers in the LOP inventory as 'Ansible Managed'.
    """
    __tablename__ = "ansible_inventory_hosts"

    id: int = db.Column(db.Integer, primary_key=True)
    hostname: str = db.Column(db.String(255), nullable=False, unique=True, index=True)
    groups: str = db.Column(db.Text, nullable=True)   # comma-separated group names
    discovered_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<AnsibleInventoryHost {self.hostname!r}>"
