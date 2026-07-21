"""
Directory Services configuration model.

Stores the LDAP/AD/FreeIPA/OpenLDAP connection settings for the portal.
There is at most one active configuration row (singleton pattern).

The bind password is stored encrypted using app.encryption (Fernet / AES).
It is NEVER logged or exposed in plaintext through the API.

Supported directory types:
  freeipa   – Red Hat FreeIPA (default uid-based users, memberOf groups)
  ad        – Microsoft Active Directory (sAMAccountName, memberOf)
  openldap  – Generic OpenLDAP / 389 Directory Server
"""
from __future__ import annotations

from datetime import datetime

from ..extensions import db

DIRECTORY_TYPES = ("freeipa", "ad", "openldap")
DISPLAY_NAMES = {
    "freeipa":  "FreeIPA",
    "ad":       "Active Directory",
    "openldap": "OpenLDAP",
}

# Default user search filters per directory type
DEFAULT_USER_FILTERS = {
    "freeipa":  "(uid={username})",
    "ad":       "(sAMAccountName={username})",
    "openldap": "(uid={username})",
}

# Default group search filters per directory type
DEFAULT_GROUP_FILTERS = {
    "freeipa":  "(objectClass=groupOfNames)",
    "ad":       "(objectClass=group)",
    "openldap": "(objectClass=groupOfNames)",
}


class DirectoryConfig(db.Model):
    """Singleton LDAP directory configuration."""

    __tablename__ = "directory_config"

    id                   = db.Column(db.Integer, primary_key=True)
    directory_type       = db.Column(db.String(20),  nullable=False, default="freeipa")
    uri                  = db.Column(db.String(255),  nullable=False, default="")
    port                 = db.Column(db.Integer,      nullable=True)  # None = use URI default
    base_dn              = db.Column(db.String(255),  nullable=False, default="")
    bind_dn              = db.Column(db.String(255),  nullable=False, default="")
    bind_password_enc    = db.Column(db.Text,         nullable=True)  # Fernet-encrypted
    user_search_base     = db.Column(db.String(255),  nullable=True)  # defaults to base_dn
    group_search_base    = db.Column(db.String(255),  nullable=True)  # defaults to base_dn
    user_search_filter   = db.Column(db.String(255),  nullable=False, default="(uid={username})")
    group_search_filter  = db.Column(db.String(255),  nullable=False, default="(objectClass=groupOfNames)")
    ssl_enabled          = db.Column(db.Boolean,      nullable=False, default=True)
    verify_cert          = db.Column(db.Boolean,      nullable=False, default=True)
    ca_cert_path         = db.Column(db.String(500),  nullable=True)
    timeout              = db.Column(db.Integer,      nullable=False, default=10)
    default_role         = db.Column(db.String(32),   nullable=False, default="operator")
    is_enabled           = db.Column(db.Boolean,      nullable=False, default=False)
    created_at           = db.Column(db.DateTime,     nullable=False, default=datetime.utcnow)
    updated_at           = db.Column(db.DateTime,     nullable=False, default=datetime.utcnow,
                                     onupdate=datetime.utcnow)

    # ── Helpers ────────────────────────────────────────────────────────── #

    @classmethod
    def get(cls) -> "DirectoryConfig | None":
        """Return the single configuration row, or None if not yet created."""
        return cls.query.first()

    @classmethod
    def get_or_create(cls) -> "DirectoryConfig":
        """Return the config row, creating a default one if absent."""
        cfg = cls.get()
        if cfg is None:
            cfg = cls()
            db.session.add(cfg)
            db.session.commit()
        return cfg

    def set_bind_password(self, plaintext: str) -> None:
        """Encrypt and store the bind password."""
        if not plaintext:
            self.bind_password_enc = None
            return
        from ..encryption import encrypt_value
        self.bind_password_enc = encrypt_value(plaintext)

    def get_bind_password(self) -> str | None:
        """Decrypt and return the bind password, or None on failure."""
        if not self.bind_password_enc:
            return None
        from ..encryption import decrypt_value
        return decrypt_value(self.bind_password_enc)

    @property
    def display_type(self) -> str:
        return DISPLAY_NAMES.get(self.directory_type, self.directory_type)

    @property
    def effective_user_search_base(self) -> str:
        return self.user_search_base or self.base_dn

    @property
    def effective_group_search_base(self) -> str:
        return self.group_search_base or self.base_dn

    def __repr__(self) -> str:
        return f"<DirectoryConfig type={self.directory_type!r} uri={self.uri!r} enabled={self.is_enabled}>"
