"""
FreeIPA LDAP authentication service.

Provides authenticate() and test_connection() against a FreeIPA LDAP directory.
All configuration is read from the Flask app config (sourced from env vars):

  FREEIPA_ENABLED      – "true" to activate (default: "false")
  FREEIPA_URI          – e.g. "ldaps://ipa.example.com"
  FREEIPA_BASE_DN      – e.g. "dc=example,dc=com"
  FREEIPA_BIND_DN      – service-account DN for lookups
  FREEIPA_BIND_PASSWORD– service-account password (never stored for end users)
  FREEIPA_CA_CERT      – absolute path to PEM CA bundle (optional)
  FREEIPA_VERIFY_CERT  – "false" to skip TLS verification (dev only, default true)

Role mapping from memberOf attribute:
  cn=LinuxAdmins,*    → administrator
  cn=LinuxOperators,* → operator
  cn=LinuxReadOnly,*  → readonly
  (no match)          → operator  (safe default)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Sentinel returned when FreeIPA is disabled
_DISABLED = object()

# Group CN → portal role
_GROUP_ROLE_MAP = {
    "LinuxAdmins":    "administrator",
    "LinuxOperators": "operator",
    "LinuxReadOnly":  "readonly",
}


@dataclass
class AuthResult:
    """Returned by FreeIPAService.authenticate()."""
    success: bool = False
    username: str = ""
    display_name: str = ""
    email: str = ""
    role: str = "operator"
    error: str = ""


@dataclass
class ConnectionResult:
    """Returned by FreeIPAService.test_connection()."""
    success: bool = False
    message: str = ""
    server: str = ""
    base_dn: str = ""


class FreeIPAService:
    """Thin wrapper around ldap3 for FreeIPA authentication."""

    def __init__(self, app_config: dict):
        self._enabled = str(app_config.get("FREEIPA_ENABLED", "false")).lower() == "true"
        self._uri = app_config.get("FREEIPA_URI", "")
        self._base_dn = app_config.get("FREEIPA_BASE_DN", "")
        self._bind_dn = app_config.get("FREEIPA_BIND_DN", "")
        self._bind_password = app_config.get("FREEIPA_BIND_PASSWORD", "")
        self._ca_cert = app_config.get("FREEIPA_CA_CERT", "")
        self._verify_cert = str(app_config.get("FREEIPA_VERIFY_CERT", "true")).lower() != "false"

    # ── Public API ──────────────────────────────────────────────────────── #

    @property
    def enabled(self) -> bool:
        return self._enabled

    def authenticate(self, username: str, password: str) -> AuthResult:
        """
        Authenticate a user against FreeIPA LDAP.

        Steps:
          1. Bind with the service account to look up the user's DN.
          2. Re-bind with the user's DN + supplied password.
          3. Read cn, mail, memberOf to fill the AuthResult.

        Returns AuthResult(success=False) on any failure without raising.
        """
        if not self._enabled:
            return AuthResult(error="FreeIPA authentication is not enabled.")

        try:
            import ldap3
        except ImportError:
            logger.error("ldap3 package is not installed; cannot perform LDAP auth")
            return AuthResult(error="LDAP library not available.")

        try:
            tls = self._build_tls(ldap3)
            server = ldap3.Server(self._uri, tls=tls, get_info=ldap3.NONE)

            # Step 1: service-account lookup
            with ldap3.Connection(
                server,
                user=self._bind_dn,
                password=self._bind_password,
                auto_bind=ldap3.AUTO_BIND_TLS_BEFORE_BIND if self._uri.startswith("ldap://") else True,
                raise_exceptions=True,
            ) as conn:
                user_dn, attrs = self._lookup_user(conn, ldap3, username)
                if not user_dn:
                    return AuthResult(error="User not found in directory.")

            # Step 2: bind as the user to verify password
            with ldap3.Connection(
                server,
                user=user_dn,
                password=password,
                auto_bind=ldap3.AUTO_BIND_TLS_BEFORE_BIND if self._uri.startswith("ldap://") else True,
                raise_exceptions=True,
            ):
                pass  # bind success means password is correct

            # Step 3: map attributes
            role = self._map_role(attrs.get("memberOf", []))
            display_name = self._first(attrs.get("cn", []), username)
            email = self._first(attrs.get("mail", []), "")

            logger.info(
                "FreeIPA auth success: username=%s role=%s dn=%s",
                username, role, user_dn,
            )
            return AuthResult(
                success=True,
                username=username,
                display_name=display_name,
                email=email,
                role=role,
            )

        except Exception as exc:
            # ldap3 raises LDAPBindError for wrong password
            exc_name = type(exc).__name__
            if "Bind" in exc_name or "InvalidCredentials" in exc_name:
                logger.warning("FreeIPA bind failed for user '%s': %s", username, exc)
                return AuthResult(error="Invalid username or password.")
            logger.exception("FreeIPA authentication error for user '%s'", username)
            return AuthResult(error=f"LDAP error: {exc_name}")

    def test_connection(self) -> ConnectionResult:
        """
        Verify the service-account bind works.  Used by the Settings page.
        Returns ConnectionResult with success/message/server/base_dn.
        """
        if not self._enabled:
            return ConnectionResult(
                success=False,
                message="FreeIPA integration is disabled (FREEIPA_ENABLED is not set to true).",
            )

        try:
            import ldap3
        except ImportError:
            return ConnectionResult(success=False, message="ldap3 package is not installed.")

        try:
            tls = self._build_tls(ldap3)
            server = ldap3.Server(self._uri, tls=tls, get_info=ldap3.ALL)
            with ldap3.Connection(
                server,
                user=self._bind_dn,
                password=self._bind_password,
                auto_bind=ldap3.AUTO_BIND_TLS_BEFORE_BIND if self._uri.startswith("ldap://") else True,
                raise_exceptions=True,
            ) as conn:
                server_info = str(conn.server.info.vendor_name or "LDAP server") if conn.server.info else self._uri
                logger.info("FreeIPA test_connection success: uri=%s", self._uri)
                return ConnectionResult(
                    success=True,
                    message=f"Connected successfully to {server_info}.",
                    server=self._uri,
                    base_dn=self._base_dn,
                )
        except Exception as exc:
            logger.warning("FreeIPA test_connection failed: %s", exc)
            return ConnectionResult(
                success=False,
                message=f"Connection failed: {type(exc).__name__}: {exc}",
                server=self._uri,
                base_dn=self._base_dn,
            )

    # ── Private helpers ─────────────────────────────────────────────────── #

    def _build_tls(self, ldap3):
        """Build an ldap3 Tls object from config."""
        import ssl
        if not self._verify_cert:
            return ldap3.Tls(validate=ssl.CERT_NONE)
        if self._ca_cert:
            return ldap3.Tls(ca_certs_file=self._ca_cert, validate=ssl.CERT_REQUIRED)
        return ldap3.Tls(validate=ssl.CERT_REQUIRED)

    def _lookup_user(self, conn, ldap3, username: str) -> tuple[str, dict]:
        """Search for the user by uid; return (dn, attribute_dict)."""
        safe_username = ldap3.utils.conv.escape_filter_chars(username)
        conn.search(
            search_base=self._base_dn,
            search_filter=f"(&(objectClass=person)(uid={safe_username}))",
            search_scope=ldap3.SUBTREE,
            attributes=["cn", "mail", "memberOf", "uid"],
        )
        if not conn.entries:
            return "", {}

        entry = conn.entries[0]
        attrs = {
            "cn":       list(entry.cn)       if hasattr(entry, "cn")       else [],
            "mail":     list(entry.mail)      if hasattr(entry, "mail")     else [],
            "memberOf": list(entry.memberOf)  if hasattr(entry, "memberOf") else [],
        }
        return entry.entry_dn, attrs

    @staticmethod
    def _map_role(member_of: list[str]) -> str:
        """
        Derive portal role from memberOf DNs.

        Priority: administrator > operator > readonly.
        Falls back to "operator" if no matching group is found.
        """
        cns = set()
        for dn in member_of:
            for part in dn.split(","):
                part = part.strip()
                if part.upper().startswith("CN="):
                    cns.add(part[3:])

        # Evaluate in priority order
        for group_cn, role in _GROUP_ROLE_MAP.items():
            if group_cn in cns:
                return role

        return "operator"

    @staticmethod
    def _first(values: list, default: str) -> str:
        return str(values[0]) if values else default
