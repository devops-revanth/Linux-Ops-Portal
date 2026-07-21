"""
LDAP / Directory Services authentication.

Supports FreeIPA, Active Directory, and OpenLDAP via ldap3.

Configuration is loaded from the DirectoryConfig database record (managed
through Settings → Directory Services).  If no database record exists the
service falls back to the legacy FREEIPA_* environment variables so that
existing deployments keep working without re-configuration.

Role mapping is read from the LdapGroupMapping table (configurable through
the Settings UI) rather than being hard-coded.

Public interface:
    svc = FreeIPAService.from_app()   # preferred — loads from DB
    svc = FreeIPAService(app_config)  # legacy — reads env vars

    result = svc.authenticate(username, password)  → AuthResult
    result = svc.test_connection()                 → ConnectionResult
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Priority order: higher index = lower priority
_ROLE_PRIORITY = {"administrator": 0, "operator": 1, "readonly": 2}


@dataclass
class AuthResult:
    success: bool = False
    username: str = ""
    display_name: str = ""
    email: str = ""
    role: str = "operator"
    error: str = ""


@dataclass
class ConnectionResult:
    success: bool = False
    message: str = ""
    server: str = ""
    base_dn: str = ""


# ── Internal config holder ─────────────────────────────────────────────────── #

class _LdapConfig:
    """Normalised LDAP settings regardless of source (DB or env vars)."""

    def __init__(
        self,
        enabled: bool,
        directory_type: str,
        uri: str,
        base_dn: str,
        bind_dn: str,
        bind_password: str,
        user_search_base: str,
        group_search_base: str,
        user_search_filter: str,
        group_search_filter: str,
        verify_cert: bool,
        ca_cert_path: str,
        timeout: int,
        default_role: str,
        group_mappings: list[tuple[str, str]],  # [(group_dn, role), ...]
    ):
        self.enabled             = enabled
        self.directory_type      = directory_type
        self.uri                 = uri
        self.base_dn             = base_dn
        self.bind_dn             = bind_dn
        self.bind_password       = bind_password
        self.user_search_base    = user_search_base or base_dn
        self.group_search_base   = group_search_base or base_dn
        self.user_search_filter  = user_search_filter  # e.g. "(uid={username})"
        self.group_search_filter = group_search_filter
        self.verify_cert         = verify_cert
        self.ca_cert_path        = ca_cert_path
        self.timeout             = timeout
        self.default_role        = default_role
        self.group_mappings      = group_mappings  # sorted externally if needed


# ── Main service ──────────────────────────────────────────────────────────── #

class FreeIPAService:
    """LDAP authentication service — works with FreeIPA, AD, and OpenLDAP."""

    def __init__(self, app_config: dict):
        """Legacy constructor: reads FREEIPA_* environment variables."""
        enabled      = str(app_config.get("FREEIPA_ENABLED", "false")).lower() == "true"
        uri          = app_config.get("FREEIPA_URI", "")
        base_dn      = app_config.get("FREEIPA_BASE_DN", "")
        bind_dn      = app_config.get("FREEIPA_BIND_DN", "")
        bind_pass    = app_config.get("FREEIPA_BIND_PASSWORD", "")
        ca_cert      = app_config.get("FREEIPA_CA_CERT", "")
        verify_cert  = str(app_config.get("FREEIPA_VERIFY_CERT", "true")).lower() != "false"

        self._cfg = _LdapConfig(
            enabled             = enabled,
            directory_type      = "freeipa",
            uri                 = uri,
            base_dn             = base_dn,
            bind_dn             = bind_dn,
            bind_password       = bind_pass,
            user_search_base    = base_dn,
            group_search_base   = base_dn,
            user_search_filter  = "(uid={username})",
            group_search_filter = "(objectClass=groupOfNames)",
            verify_cert         = verify_cert,
            ca_cert_path        = ca_cert,
            timeout             = 10,
            default_role        = "operator",
            group_mappings      = [
                ("LinuxAdmins",    "administrator"),
                ("LinuxOperators", "operator"),
                ("LinuxReadOnly",  "readonly"),
            ],
        )

    @classmethod
    def from_db(cls) -> "FreeIPAService":
        """
        Preferred constructor: load config from the DirectoryConfig DB record.
        Falls back to a disabled service if no record exists.
        """
        inst = cls.__new__(cls)
        try:
            from .models.directory_config import DirectoryConfig
            from .models.ldap_group_mapping import LdapGroupMapping

            db_cfg = DirectoryConfig.get()
            if db_cfg is None:
                inst._cfg = _LdapConfig(
                    enabled=False, directory_type="freeipa", uri="",
                    base_dn="", bind_dn="", bind_password="",
                    user_search_base="", group_search_base="",
                    user_search_filter="(uid={username})",
                    group_search_filter="(objectClass=groupOfNames)",
                    verify_cert=True, ca_cert_path="",
                    timeout=10, default_role="operator", group_mappings=[],
                )
                return inst

            bind_pass = db_cfg.get_bind_password() or ""
            mappings  = [
                (m.group_dn, m.role)
                for m in LdapGroupMapping.query.order_by(
                    LdapGroupMapping.role
                ).all()
            ]

            inst._cfg = _LdapConfig(
                enabled             = db_cfg.is_enabled,
                directory_type      = db_cfg.directory_type,
                uri                 = db_cfg.uri,
                base_dn             = db_cfg.base_dn,
                bind_dn             = db_cfg.bind_dn,
                bind_password       = bind_pass,
                user_search_base    = db_cfg.effective_user_search_base,
                group_search_base   = db_cfg.effective_group_search_base,
                user_search_filter  = db_cfg.user_search_filter,
                group_search_filter = db_cfg.group_search_filter,
                verify_cert         = db_cfg.verify_cert,
                ca_cert_path        = db_cfg.ca_cert_path or "",
                timeout             = db_cfg.timeout,
                default_role        = db_cfg.default_role,
                group_mappings      = mappings,
            )
        except Exception as exc:
            logger.warning("FreeIPAService.from_db failed, using disabled service: %s", exc)
            inst._cfg = _LdapConfig(
                enabled=False, directory_type="freeipa", uri="",
                base_dn="", bind_dn="", bind_password="",
                user_search_base="", group_search_base="",
                user_search_filter="(uid={username})",
                group_search_filter="(objectClass=groupOfNames)",
                verify_cert=True, ca_cert_path="",
                timeout=10, default_role="operator", group_mappings=[],
            )
        return inst

    # ── Public API ─────────────────────────────────────────────────────── #

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled

    def authenticate(self, username: str, password: str) -> AuthResult:
        """Bind-test the user against the configured LDAP directory."""
        if not self._cfg.enabled:
            return AuthResult(error="Directory authentication is not enabled.")

        try:
            import ldap3
        except ImportError:
            logger.error("ldap3 not installed; cannot perform LDAP authentication")
            return AuthResult(error="LDAP library not available.")

        try:
            tls    = self._build_tls(ldap3)
            server = ldap3.Server(
                self._cfg.uri, tls=tls,
                get_info=ldap3.NONE,
                connect_timeout=self._cfg.timeout,
            )
            use_starttls = self._cfg.uri.startswith("ldap://") and self._cfg.verify_cert

            # Step 1: service-account lookup
            with ldap3.Connection(
                server, user=self._cfg.bind_dn, password=self._cfg.bind_password,
                auto_bind=ldap3.AUTO_BIND_TLS_BEFORE_BIND if use_starttls else True,
                raise_exceptions=True,
            ) as conn:
                user_dn, attrs = self._lookup_user(conn, ldap3, username)
                if not user_dn:
                    return AuthResult(error="User not found in directory.")

            # Step 2: bind as the user to verify password
            with ldap3.Connection(
                server, user=user_dn, password=password,
                auto_bind=ldap3.AUTO_BIND_TLS_BEFORE_BIND if use_starttls else True,
                raise_exceptions=True,
            ):
                pass

            # Step 3: map role
            role = self._map_role(attrs.get("memberOf", []))
            display_name = self._first(attrs.get("cn", []) or attrs.get("displayName", []), username)
            email = self._first(attrs.get("mail", []), "")

            logger.info("LDAP auth success: username=%s role=%s", username, role)
            return AuthResult(
                success=True, username=username,
                display_name=display_name, email=email, role=role,
            )

        except Exception as exc:
            exc_name = type(exc).__name__
            if any(k in exc_name for k in ("Bind", "InvalidCredentials", "AuthenticationFailed")):
                logger.warning("LDAP bind failed for '%s': %s", username, exc)
                return AuthResult(error="Invalid username or password.")
            logger.exception("LDAP authentication error for '%s'", username)
            return AuthResult(error=f"Directory error: {exc_name}")

    def test_connection(self) -> ConnectionResult:
        """Verify service-account bind.  Returns ConnectionResult."""
        if not self._cfg.enabled:
            return ConnectionResult(
                success=False,
                message="Directory authentication is disabled.",
            )
        try:
            import ldap3
        except ImportError:
            return ConnectionResult(success=False, message="ldap3 package is not installed.")

        try:
            tls    = self._build_tls(ldap3)
            server = ldap3.Server(
                self._cfg.uri, tls=tls,
                get_info=ldap3.ALL,
                connect_timeout=self._cfg.timeout,
            )
            use_starttls = self._cfg.uri.startswith("ldap://") and self._cfg.verify_cert
            with ldap3.Connection(
                server, user=self._cfg.bind_dn, password=self._cfg.bind_password,
                auto_bind=ldap3.AUTO_BIND_TLS_BEFORE_BIND if use_starttls else True,
                raise_exceptions=True,
            ) as conn:
                vendor = ""
                try:
                    vendor = str(conn.server.info.vendor_name or "")
                except Exception:
                    pass
                msg = f"Connected successfully to {vendor or self._cfg.uri}."
                logger.info("Directory test_connection success: uri=%s", self._cfg.uri)
                return ConnectionResult(
                    success=True, message=msg,
                    server=self._cfg.uri, base_dn=self._cfg.base_dn,
                )
        except Exception as exc:
            logger.warning("Directory test_connection failed: %s", exc)
            return ConnectionResult(
                success=False,
                message=f"Connection failed: {type(exc).__name__}: {exc}",
                server=self._cfg.uri, base_dn=self._cfg.base_dn,
            )

    # ── Private helpers ─────────────────────────────────────────────────── #

    def _build_tls(self, ldap3):
        import ssl
        if not self._cfg.verify_cert:
            return ldap3.Tls(validate=ssl.CERT_NONE)
        if self._cfg.ca_cert_path:
            return ldap3.Tls(ca_certs_file=self._cfg.ca_cert_path, validate=ssl.CERT_REQUIRED)
        return ldap3.Tls(validate=ssl.CERT_REQUIRED)

    def _lookup_user(self, conn, ldap3, username: str) -> tuple[str, dict]:
        safe_username = ldap3.utils.conv.escape_filter_chars(username)
        search_filter = self._cfg.user_search_filter.replace("{username}", safe_username)
        attrs = ["cn", "displayName", "mail", "memberOf", "uid", "sAMAccountName"]
        conn.search(
            search_base   = self._cfg.user_search_base,
            search_filter = search_filter,
            search_scope  = ldap3.SUBTREE,
            attributes    = attrs,
        )
        if not conn.entries:
            return "", {}
        entry = conn.entries[0]

        def _list(attr):
            try:
                return list(getattr(entry, attr)) if hasattr(entry, attr) else []
            except Exception:
                return []

        return entry.entry_dn, {
            "cn":          _list("cn"),
            "displayName": _list("displayName"),
            "mail":        _list("mail"),
            "memberOf":    _list("memberOf"),
        }

    def _map_role(self, member_of: list[str]) -> str:
        """
        Derive role from the LdapGroupMapping table.

        Matches each memberOf DN against stored group_dn values.
        The matching uses both full-DN equality and CN-prefix matching so
        administrators can store either full DNs or just the CN component.
        Priority: administrator > operator > readonly > default_role.
        """
        if not self._cfg.group_mappings:
            return self._cfg.default_role

        # Extract CN components from the memberOf list
        member_cns: set[str] = set()
        member_dns: set[str] = {dn.lower() for dn in member_of}
        for dn in member_of:
            for part in dn.split(","):
                part = part.strip()
                if part.upper().startswith("CN="):
                    member_cns.add(part[3:].lower())

        best_priority = len(_ROLE_PRIORITY) + 1
        best_role = self._cfg.default_role

        for group_dn, role in self._cfg.group_mappings:
            group_lower = group_dn.lower().strip()
            matched = (
                group_lower in member_dns
                or group_lower in member_cns
            )
            if matched:
                priority = _ROLE_PRIORITY.get(role, 99)
                if priority < best_priority:
                    best_priority = priority
                    best_role = role

        return best_role

    @staticmethod
    def _first(values: list, default: str) -> str:
        return str(values[0]) if values else default
