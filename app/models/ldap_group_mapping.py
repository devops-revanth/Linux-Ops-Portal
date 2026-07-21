"""
LDAP group → portal role mapping model.

Administrators define which LDAP group DN (or CN) maps to which portal role.
These are evaluated in priority order: administrator > operator > readonly.

Example mappings:
  cn=LinuxAdmins,cn=groups,dc=example,dc=com  → administrator
  cn=LinuxOps,cn=groups,dc=example,dc=com     → operator
  cn=LinuxReadOnly,cn=groups,dc=example,dc=com → readonly
"""
from datetime import datetime

from ..extensions import db

VALID_ROLES = ("administrator", "operator", "readonly")

# Priority order for role evaluation (highest first)
ROLE_PRIORITY = {role: i for i, role in enumerate(VALID_ROLES)}


class LdapGroupMapping(db.Model):
    """Maps an LDAP group DN to a portal role."""

    __tablename__ = "ldap_group_mappings"

    id         = db.Column(db.Integer, primary_key=True)
    group_dn   = db.Column(db.String(500), nullable=False, unique=True, index=True)
    role       = db.Column(db.String(32),  nullable=False, default="operator")
    created_at = db.Column(db.DateTime,   nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<LdapGroupMapping {self.group_dn!r} → {self.role!r}>"
