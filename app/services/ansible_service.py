"""
Ansible control node service — SSH-based connection validation,
inventory inspection, and playbook discovery.

This module only reads from the control node; it never executes
playbooks, modifies servers, or runs ad-hoc commands.

All SSH operations use paramiko.  Credentials are NEVER logged,
included in exceptions, or returned in API responses.
"""
from __future__ import annotations

import io
import json
import logging
import os
import pwd
import re
from typing import Any

logger = logging.getLogger(__name__)

# Status strings — must match CONNECTION_STATUS_OPTIONS in ansible_config.py
_STATUS_CONNECTED             = "Connected"
_STATUS_DISCONNECTED          = "Disconnected"
_STATUS_AUTH_FAILED           = "Authentication Failed"
_STATUS_HOST_KEY_MISMATCH     = "Host Key Mismatch"
_STATUS_INVENTORY_MISSING     = "Inventory Missing"
_STATUS_PLAYBOOK_DIR_MISSING  = "Playbook Directory Missing"
_STATUS_ANSIBLE_NOT_INSTALLED = "Ansible Not Installed"
_STATUS_TIMEOUT               = "Connection Timeout"


class AnsibleConnectionError(Exception):
    """Raised when SSH connection or authentication fails."""

    def __init__(self, message: str, status: str = _STATUS_DISCONNECTED):
        super().__init__(message)
        self.status = status


class AnsibleService:
    """SSH-based interface to an Ansible control node."""

    # ── Construction ──────────────────────────────────────────────────────── #

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        auth_method: str,           # "key" | "password"
        ssh_password: str = "",
        ssh_private_key: str = "",  # PEM text
        host_key_checking: bool = True,
        timeout: int = 30,
        inventory_path: str = "/etc/ansible/hosts",
        playbook_dir: str = "/etc/ansible/playbooks",
    ):
        self.host              = host
        self.port              = port
        self.username          = username
        self.auth_method       = auth_method
        self.ssh_password      = ssh_password
        self.ssh_private_key   = ssh_private_key
        self.host_key_checking = host_key_checking
        self.timeout           = timeout
        self.inventory_path    = inventory_path   # plain attribute, no mangling
        self.playbook_dir      = playbook_dir     # plain attribute, no mangling

    @classmethod
    def from_config(cls, cfg) -> "AnsibleService":
        """Build an AnsibleService from an AnsibleConfig model instance."""
        return cls(
            host              = cfg.control_node or "",
            port              = cfg.port or 22,
            username          = cfg.username or "",
            auth_method       = cfg.auth_method or "key",
            ssh_password      = cfg.get_ssh_password() or "",
            ssh_private_key   = cfg.get_ssh_private_key() or "",
            host_key_checking = cfg.host_key_checking,
            timeout           = cfg.connection_timeout or 30,
            inventory_path    = cfg.inventory_path or "/etc/ansible/hosts",
            playbook_dir      = cfg.playbook_dir or "/etc/ansible/playbooks",
        )

    # ── Low-level SSH ─────────────────────────────────────────────────────── #

    def _connect(self):
        """
        Open a paramiko SSHClient to the control node.

        Returns a connected SSHClient.  Raises AnsibleConnectionError with a
        specific, actionable message on any failure.
        The private key and password are NEVER included in log output.
        """
        try:
            import paramiko  # type: ignore
        except ImportError:
            raise AnsibleConnectionError(
                "paramiko is not installed. Run: pip install paramiko",
                status=_STATUS_DISCONNECTED,
            )

        # Resolve the known_hosts file from the SSH user's home directory,
        # NOT from the backend service account (lop).  The service account
        # runs as a no-login system user and has no SSH configuration of its
        # own; os.path.expanduser("~") and load_system_host_keys() would
        # both resolve to /opt/lop/.ssh which is wrong.
        known_hosts = self._known_hosts_path(self.username)

        logger.debug(
            "_connect: host=%s port=%s user=%r auth_method=%s timeout=%ss "
            "host_key_checking=%s",
            self.host, self.port, self.username,
            self.auth_method, self.timeout, self.host_key_checking,
        )
        logger.debug("_connect: known_hosts=%s (exists=%s)", known_hosts, os.path.isfile(known_hosts))

        client = paramiko.SSHClient()
        if self.host_key_checking:
            # ── Step 1: read the file ourselves so we get a clear error ───
            # os.path.isfile() masks PermissionError as "not found".
            # open() raises PermissionError directly, which lets us give an
            # actionable message with the exact chmod/setfacl command.
            raw_data_lines: list[str] = []
            try:
                with open(known_hosts, "r") as _f:
                    for _line in _f:
                        _s = _line.strip()
                        if _s and not _s.startswith("#"):
                            raw_data_lines.append(_s)
                logger.debug(
                    "_connect: known_hosts readable — %d data line(s) found",
                    len(raw_data_lines),
                )
            except FileNotFoundError:
                logger.warning(
                    "_connect: known_hosts not found at %s — strict host key "
                    "checking is ON but no known_hosts file exists; every "
                    "connection attempt will be rejected by RejectPolicy",
                    known_hosts,
                )
            except PermissionError:
                # Surface this before any SSH attempt so the admin sees the
                # real cause rather than "Server X not found in known_hosts".
                raise AnsibleConnectionError(
                    f"Permission Denied: The LOP service account cannot read "
                    f"{known_hosts}.\n"
                    f"Grant read access to the service account with:\n"
                    f"  sudo setfacl -m u:lop:x {os.path.dirname(known_hosts)}\n"
                    f"  sudo setfacl -m u:lop:r {known_hosts}\n"
                    f"Or run: sudo chmod o+r {known_hosts} && "
                    f"sudo chmod o+x {os.path.dirname(known_hosts)}\n"
                    f"Or disable Strict Host Key Checking in LOP settings.",
                    status=_STATUS_DISCONNECTED,
                )

            # ── Step 2: load into paramiko ────────────────────────────────
            # Only attempt load if we successfully read at least one line.
            if raw_data_lines:
                client.load_host_keys(known_hosts)

                # Verify: how many entries did paramiko actually parse?
                # Hashed entries (ssh-keyscan -H) appear as '|1|...' keys —
                # that is correct; paramiko resolves them via HMAC inside
                # connect() and we must NOT do a manual lookup here.
                loaded_keys = client.get_host_keys()
                entry_list  = list(loaded_keys.keys())
                logger.debug(
                    "_connect: known_hosts loaded\n"
                    "  path            : %s\n"
                    "  paramiko version: %s\n"
                    "  raw data lines  : %d\n"
                    "  entries loaded  : %d\n"
                    "  entry keys      : %s\n"
                    "  target host     : %s",
                    known_hosts,
                    paramiko.__version__,
                    len(raw_data_lines),
                    len(entry_list),
                    entry_list if len(entry_list) <= 20 else entry_list[:20] + ["…"],
                    self.host,
                )

                if len(entry_list) == 0:
                    # All lines were read but nothing parsed — log the
                    # hostname fields only (first token of each line) so
                    # the format is visible without exposing key material.
                    samples = [l.split()[0] for l in raw_data_lines[:5] if l.split()]
                    logger.warning(
                        "_connect: known_hosts has %d raw line(s) but 0 "
                        "entries were loaded by paramiko %s — all lines "
                        "failed to parse.  Hostname field samples: %s",
                        len(raw_data_lines),
                        paramiko.__version__,
                        samples,
                    )

            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            logger.debug("_connect: host key checking disabled — AutoAddPolicy")

        connect_kwargs: dict[str, Any] = {
            "hostname":       self.host,
            "port":           self.port,
            "username":       self.username,
            "timeout":        self.timeout,
            "banner_timeout": self.timeout,
            "auth_timeout":   self.timeout,
        }

        if self.auth_method == "key" and self.ssh_private_key:
            # _load_private_key sanitises the key text (CRLF, trailing
            # whitespace, blank lines) before handing it to paramiko.
            pkey = self._load_private_key(self.ssh_private_key)
            logger.debug("_connect: using pkey type=%s", type(pkey).__name__)
            connect_kwargs["pkey"]          = pkey
            connect_kwargs["look_for_keys"] = False
            connect_kwargs["allow_agent"]   = False
        elif self.auth_method == "password" and self.ssh_password:
            logger.debug("_connect: using password auth")
            connect_kwargs["password"]      = self.ssh_password
            connect_kwargs["look_for_keys"] = False
            connect_kwargs["allow_agent"]   = False
        else:
            # Fall back to SSH agent / default key locations
            logger.debug("_connect: using agent/default-key fallback")
            connect_kwargs["look_for_keys"] = True
            connect_kwargs["allow_agent"]   = True

        try:
            client.connect(**connect_kwargs)
            logger.debug("_connect: connected successfully to %s:%s", self.host, self.port)
            return client

        except Exception as exc:
            client.close()
            exc_type = type(exc).__name__
            exc_msg  = str(exc)
            # Log the real exception at DEBUG so administrators can diagnose
            # failures without credentials ever appearing in the output.
            logger.debug(
                "_connect: failed to %s:%s — %s: %s",
                self.host, self.port, exc_type, exc_msg,
            )

            # ── BadHostKeyException ────────────────────────────────────────
            # Host IS in known_hosts but the key presented by the server
            # does not match.  This is the only host-key classification LOP
            # performs itself; everything else comes verbatim from paramiko.
            if exc_type == "BadHostKeyException":
                raise AnsibleConnectionError(
                    f"Host Key Mismatch: The host key for {self.host} does "
                    f"not match the entry in {known_hosts}. "
                    f"If the host was rebuilt, remove the old entry with:\n"
                    f"  ssh-keygen -R {self.host} -f {known_hosts}\n"
                    f"Or disable Strict Host Key Checking in LOP settings.",
                    status=_STATUS_HOST_KEY_MISMATCH,
                )

            # ── Authentication failure ─────────────────────────────────────
            if exc_type == "AuthenticationException":
                raise AnsibleConnectionError(
                    f"Authentication Failed: Could not authenticate to "
                    f"{self.host}:{self.port} as '{self.username}'. "
                    f"Check the username and SSH key/password.",
                    status=_STATUS_AUTH_FAILED,
                )

            # ── Network / reachability failures ───────────────────────────
            if exc_type in ("NoValidConnectionsError", "ConnectionRefusedError",
                            "TimeoutError", "socket.timeout"):
                raise AnsibleConnectionError(
                    f"Host Unreachable: Could not reach {self.host}:{self.port}. "
                    f"Check that the host is reachable and port {self.port} "
                    f"is open ({exc_type}).",
                    status=_STATUS_TIMEOUT,
                )

            # ── All other exceptions: surface verbatim ────────────────────
            # Do NOT reclassify paramiko's own messages (e.g. SSHException
            # "Server X not found in known_hosts") — paramiko is the sole
            # authority on host key verification results.
            raise AnsibleConnectionError(
                f"{exc_type}: {exc_msg}",
                status=_STATUS_DISCONNECTED,
            )

    @staticmethod
    def _known_hosts_path(username: str) -> str:
        """
        Return the known_hosts path for *username*, resolved via the local
        passwd database.

        The backend service runs as the ``lop`` system account.  SSH
        operations connect as a completely different user (e.g. ``ansible``).
        Using os.path.expanduser("~") or paramiko's load_system_host_keys()
        would resolve to /opt/lop/.ssh — the service account's home — which
        is wrong.  This helper looks up the SSH user's home directory from
        /etc/passwd instead.

        If the SSH user does not exist locally (it lives only on the remote
        control node), the lookup raises KeyError and we fall back to the
        conventional /home/<username> path, which is correct for the typical
        Ansible managed-node layout.
        """
        try:
            home = pwd.getpwnam(username).pw_dir
        except KeyError:
            home = os.path.join("/home", username)
        return os.path.join(home, ".ssh", "known_hosts")

    @staticmethod
    def _sanitize_key_text(raw: str) -> str:
        """
        Normalize a PEM/OpenSSH private key string before handing it to paramiko.

        Web browser textareas introduce several problems that cause paramiko to
        silently reject an otherwise valid key:

        * Windows CRLF line endings (\\r\\n) — the PEM parser expects bare LF
        * Trailing spaces on lines — confuses the base64 decoder
        * Leading / trailing blank lines — PEM expects the header on line 1
        * Missing final newline — some paramiko versions require it

        None of these issues appear when using ``ssh -i`` because the OpenSSH
        client reads the file directly from disk.  The web UI is the source of
        all four.
        """
        # Normalise all line endings to LF
        text = raw.replace("\r\n", "\n").replace("\r", "\n")
        # Strip trailing whitespace from every line (safe — base64 has no spaces)
        lines = [line.rstrip() for line in text.splitlines()]
        # Remove leading and trailing blank lines
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        # Ensure exactly one trailing newline (required by some paramiko versions)
        return "\n".join(lines) + "\n"

    @staticmethod
    def _load_private_key(key_text: str):
        """
        Sanitise and auto-detect the type of an OpenSSH/PEM private key.

        Uses ``paramiko.key_classes`` — the canonical list of key types
        supported by the *installed* version of paramiko — so the code
        adapts automatically as paramiko adds or removes key types.
        DSA/DSS keys are not referenced here; DSSKey was removed from
        paramiko 3.x and must not be imported directly.

        Raises AnsibleConnectionError with a specific message on failure.
        The key material itself is never logged.
        """
        import paramiko  # type: ignore

        # Sanitise before parsing: strip CRLF, trailing whitespace, blank
        # lines.  This is the most common reason a key that works with
        # 'ssh -i' is rejected by paramiko when pasted through the UI.
        clean = AnsibleService._sanitize_key_text(key_text)
        logger.debug(
            "_load_private_key: key length %d chars (raw %d), "
            "first_line=%r",
            len(clean), len(key_text),
            clean.splitlines()[0] if clean.strip() else "(empty)",
        )

        # key_classes is the authoritative list added in paramiko 3.x.
        # Fallback: build the list from individual attributes so older
        # versions of paramiko (3.0–3.x) that may not expose key_classes
        # still work.  DSSKey is intentionally absent from the fallback.
        classes_to_try = getattr(paramiko, "key_classes", None) or [
            cls
            for cls in (
                getattr(paramiko, "RSAKey",     None),
                getattr(paramiko, "Ed25519Key", None),
                getattr(paramiko, "ECDSAKey",   None),
            )
            if cls is not None
        ]

        key_io = io.StringIO(clean)
        for key_cls in classes_to_try:
            key_io.seek(0)
            try:
                pkey = key_cls.from_private_key(key_io)
                logger.debug(
                    "_load_private_key: loaded as %s", key_cls.__name__
                )
                return pkey
            except paramiko.PasswordRequiredException:
                # The key was recognised but is passphrase-protected.
                # No point trying the other classes.
                raise AnsibleConnectionError(
                    "The SSH private key is passphrase-protected. "
                    "LOP does not currently support passphrase-protected keys. "
                    "Use an unencrypted key or switch to password authentication.",
                    status=_STATUS_AUTH_FAILED,
                )
            except Exception as exc:
                logger.debug(
                    "_load_private_key: %s rejected by %s — %s: %s",
                    key_cls.__name__, key_cls.__name__,
                    type(exc).__name__, exc,
                )
                continue

        # No key class could parse the key material.
        raise AnsibleConnectionError(
            "Unsupported or invalid SSH private key. "
            "Supported types: RSA, Ed25519, ECDSA. "
            "Ensure the key is a valid unencrypted OpenSSH or PEM private key.",
            status=_STATUS_AUTH_FAILED,
        )

    @staticmethod
    def _exec(client, command: str, timeout: int = 60) -> tuple[str, str, int]:
        """Run a remote command and return (stdout, stderr, exit_code)."""
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        stdin.close()
        out  = stdout.read().decode("utf-8", errors="replace")
        err  = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return out, err, code

    # ── Test connection ───────────────────────────────────────────────────── #

    def test_connection(self) -> dict[str, Any]:
        """
        SSH to the control node and verify Ansible installation and paths.

        Returns a dict:
          success         bool
          status          str   (matches CONNECTION_STATUS_OPTIONS)
          message         str   (human-readable summary)
          ansible_version str | None
          python_version  str | None
          inventory_ok    bool
          playbook_dir_ok bool
          checks          list[dict]  — per-check rows for the UI
        """
        result: dict[str, Any] = {
            "success":         False,
            "status":          _STATUS_DISCONNECTED,
            "message":         "",
            "ansible_version": None,
            "python_version":  None,
            "inventory_ok":    False,
            "playbook_dir_ok": False,
            "checks":          [],
        }

        # Structured diagnostic block — visible in the application log at
        # INFO level so administrators can immediately see what identity and
        # SSH configuration are being used without having to guess.
        try:
            svc_user = pwd.getpwuid(os.getuid()).pw_name
        except Exception:
            svc_user = str(os.getuid())

        known_hosts = self._known_hosts_path(self.username)
        key_summary = "(provided)" if self.ssh_private_key else "(none)"

        try:
            import paramiko as _pm
            pm_version = _pm.__version__
        except Exception:
            pm_version = "unknown"

        # os.path.isfile() masks PermissionError as False — use os.access()
        # to independently check existence vs readability for the diagnostic.
        kh_exists   = os.path.exists(known_hosts)
        kh_readable = os.access(known_hosts, os.R_OK)

        logger.info(
            "Test Connection diagnostic:\n"
            "  Backend Service User : %s\n"
            "  SSH Username         : %s\n"
            "  Control Node         : %s:%s\n"
            "  Authentication Method: %s\n"
            "  Private Key          : %s\n"
            "  Known Hosts          : %s\n"
            "    exists             : %s\n"
            "    readable by lop    : %s\n"
            "  Strict Host Check    : %s\n"
            "  Paramiko Version     : %s",
            svc_user,
            self.username,
            self.host, self.port,
            self.auth_method,
            key_summary,
            known_hosts,
            kh_exists,
            kh_readable,
            "Enabled" if self.host_key_checking else "Disabled",
            pm_version,
        )

        client = None
        try:
            client = self._connect()
            result["checks"].append({
                "label": "SSH Connection",
                "ok":    True,
                "detail": f"{self.host}:{self.port}",
            })
        except AnsibleConnectionError as exc:
            result["status"]  = exc.status
            result["message"] = str(exc)
            result["checks"].append({
                "label": "SSH Connection",
                "ok":    False,
                "detail": str(exc),
            })
            return result

        try:
            # ── Ansible version ────────────────────────────────────────────── #
            out, _, code = self._exec(client, "ansible --version 2>&1 | head -4")
            if code != 0 or "ansible" not in out.lower():
                out2, _, code2 = self._exec(
                    client, "/usr/bin/ansible --version 2>&1 | head -4"
                )
                if code2 != 0 or "ansible" not in out2.lower():
                    result["status"]  = _STATUS_ANSIBLE_NOT_INSTALLED
                    result["message"] = (
                        "Ansible is not installed on the control node, "
                        "or it is not in PATH. Install Ansible on the control "
                        "node before connecting LOP."
                    )
                    result["checks"].append({
                        "label": "Ansible Installed",
                        "ok":    False,
                        "detail": "ansible not found in PATH or /usr/bin",
                    })
                    return result
                out = out2

            version_line = out.splitlines()[0] if out.splitlines() else ""
            m = re.search(r"(\d+\.\d+[\.\d]*)", version_line)
            ansible_ver = m.group(1) if m else version_line.strip()
            result["ansible_version"] = ansible_ver
            result["checks"].append({
                "label": "Ansible Version",
                "ok":    True,
                "detail": version_line.strip(),
            })

            # ── ansible-playbook ──────────────────────────────────────────── #
            out2, _, code2 = self._exec(
                client, "ansible-playbook --version 2>&1 | head -1"
            )
            pb_ok = code2 == 0 and "ansible-playbook" in out2.lower()
            result["checks"].append({
                "label": "ansible-playbook",
                "ok":    pb_ok,
                "detail": out2.strip()[:80] if pb_ok else "Not found in PATH",
            })

            # ── Python version ─────────────────────────────────────────────── #
            out3, _, _ = self._exec(
                client, "python3 --version 2>&1 || python --version 2>&1"
            )
            py_line = out3.strip().splitlines()[0] if out3.strip() else ""
            py_ok = bool(py_line)
            result["python_version"] = py_line or None
            result["checks"].append({
                "label": "Python",
                "ok":    py_ok,
                "detail": py_line or "Not found",
            })

            # ── Inventory path ─────────────────────────────────────────────── #
            out4, _, _ = self._exec(
                client,
                f"test -e {_q(self.inventory_path)} && echo OK || echo MISSING",
            )
            inv_ok = "OK" in out4
            result["inventory_ok"] = inv_ok
            if not inv_ok:
                result["status"]  = _STATUS_INVENTORY_MISSING
                result["message"] = (
                    f"Inventory path not found on control node: "
                    f"{self.inventory_path}"
                )
            result["checks"].append({
                "label": f"Inventory ({self.inventory_path})",
                "ok":    inv_ok,
                "detail": "Exists" if inv_ok else f"Not found: {self.inventory_path}",
            })

            # ── Playbook directory ─────────────────────────────────────────── #
            out5, _, _ = self._exec(
                client,
                f"test -d {_q(self.playbook_dir)} && echo OK || echo MISSING",
            )
            pb_dir_ok = "OK" in out5
            result["playbook_dir_ok"] = pb_dir_ok
            if not pb_dir_ok and inv_ok:
                result["status"]  = _STATUS_PLAYBOOK_DIR_MISSING
                result["message"] = (
                    f"Playbook directory not found on control node: "
                    f"{self.playbook_dir}"
                )
            result["checks"].append({
                "label": f"Playbook Directory ({self.playbook_dir})",
                "ok":    pb_dir_ok,
                "detail": "Exists" if pb_dir_ok else f"Not found: {self.playbook_dir}",
            })

            # ── Final status ──────────────────────────────────────────────── #
            if inv_ok:  # inventory is the hard requirement; playbook dir is soft
                result["success"] = True
                result["status"]  = _STATUS_CONNECTED
                result["message"] = (
                    f"Connected — Ansible {ansible_ver or ''} "
                    f"on {self.host}:{self.port}"
                )

        except Exception as exc:
            # Catch-all: log the type only, never the message (may contain paths/data)
            logger.warning("Ansible test_connection unexpected error: %s", type(exc).__name__)
            result["message"] = (
                f"An unexpected error occurred during the connection test "
                f"({type(exc).__name__}). Check the application logs."
            )
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass

        return result

    # ── Inventory validation ──────────────────────────────────────────────── #

    def validate_inventory(self) -> dict[str, Any]:
        """
        Run `ansible-inventory --list` on the control node and parse the output.

        Supports all inventory types (static INI, static YAML, dynamic, directory).
        Nested/children groups are fully enumerated in group_names.
        Duplicate hostnames cannot occur — _meta.hostvars uses hostnames as keys.

        Returns:
          success     bool
          host_count  int
          group_names list[str]   — ALL groups including container groups
          hosts       list[str]   — unique hostnames/FQDNs from _meta.hostvars
          errors      list[str]   — warnings and errors from ansible-inventory
          raw_groups  dict        — group → direct host list (for group labelling)
          connected   bool        — False if SSH connection itself failed
        """
        result: dict[str, Any] = {
            "success":    False,
            "host_count": 0,
            "group_names": [],
            "hosts":      [],
            "errors":     [],
            "raw_groups": {},
            "connected":  False,
        }

        client = None
        try:
            client = self._connect()
            result["connected"] = True
        except AnsibleConnectionError as exc:
            result["errors"].append(str(exc))
            return result

        try:
            cmd = (
                f"ansible-inventory -i {_q(self.inventory_path)} --list"
                f" 2>&1"
            )
            out, _, _ = self._exec(client, cmd, timeout=90)

            # ansible-inventory --list outputs JSON, possibly preceded by
            # [WARNING] lines or deprecation notices.  Find the JSON object.
            json_start = out.find("{")
            if json_start == -1:
                result["errors"].append(
                    "ansible-inventory produced no JSON output. "
                    "Verify that ansible-inventory is installed and "
                    f"the inventory path is correct: {self.inventory_path}"
                )
                return result

            # Surface any pre-JSON text as informational warnings
            prefix = out[:json_start].strip()
            if prefix:
                for line in prefix.splitlines():
                    if line.strip():
                        result["errors"].append(f"Warning: {line.strip()}")

            try:
                data = json.loads(out[json_start:])
            except json.JSONDecodeError as exc:
                result["errors"].append(
                    f"Could not parse inventory JSON: {exc}. "
                    f"This may indicate a syntax error in the inventory file."
                )
                return result

            # ── All unique hosts ─────────────────────────────────────────── #
            # _meta.hostvars contains every managed host as a key.
            # Keys are unique by definition (dict), so no duplicates are possible.
            hostvars = data.get("_meta", {}).get("hostvars", {})
            hosts = sorted(hostvars.keys())
            result["hosts"]      = hosts
            result["host_count"] = len(hosts)

            # ── All groups (including container groups with only children) ── #
            # A group entry looks like:
            #   { "hosts": [...], "children": [...], "vars": {...} }
            # Groups that only have "children" are legitimate parent groups
            # and MUST be included — do not skip them.
            raw_groups: dict[str, list[str]] = {}
            for key, val in data.items():
                if key in ("_meta", "all"):
                    continue
                if not isinstance(val, dict):
                    continue
                # Include ALL groups regardless of whether they have direct hosts
                direct_hosts = val.get("hosts", [])
                raw_groups[key] = direct_hosts  # may be [] for container groups

            result["group_names"] = sorted(raw_groups.keys())
            result["raw_groups"]  = raw_groups
            result["success"]     = True

        except Exception as exc:
            logger.warning(
                "Ansible validate_inventory unexpected error: %s", type(exc).__name__
            )
            result["errors"].append(
                f"An unexpected error occurred during inventory validation "
                f"({type(exc).__name__}). Check the application logs."
            )
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass

        return result

    # ── Playbook discovery ────────────────────────────────────────────────── #

    def discover_playbooks(self) -> dict[str, Any]:
        """
        Find YAML playbooks in the configured playbook directory.

        Discovery only — playbooks are NEVER executed.

        Returns a dict:
          playbooks   list[dict]  — name, path, description, tags
          errors      list[str]   — connection or discovery errors
          connected   bool        — False if SSH connection itself failed
          count       int
        """
        result: dict[str, Any] = {
            "playbooks": [],
            "errors":    [],
            "connected": False,
            "count":     0,
        }

        client = None
        try:
            client = self._connect()
            result["connected"] = True
        except AnsibleConnectionError as exc:
            result["errors"].append(str(exc))
            return result

        try:
            # ── Discover YAML files ───────────────────────────────────────── #
            # maxdepth 5 covers typical role/collection layouts.
            # Exclude vault-encrypted files and known non-playbook names.
            # head -200 prevents runaway output for very large repos.
            find_cmd = (
                f"find {_q(self.playbook_dir)} -maxdepth 5 "
                r"\( -name '*.yml' -o -name '*.yaml' \) "
                r"! -name '*.vault.yml' ! -name '*.vault.yaml' "
                r"! -name 'requirements.yml' ! -name 'requirements.yaml' "
                r"-type f 2>/dev/null | sort | head -200"
            )
            out, _, _ = self._exec(client, find_cmd, timeout=30)
            paths = [p.strip() for p in out.splitlines() if p.strip()]

            if not paths:
                result["errors"].append(
                    f"No YAML files found in {self.playbook_dir}. "
                    f"Verify the playbook directory path is correct."
                )
                return result

            # ── Read name/tags from each file (one batched SSH command) ───── #
            # Emit a sentinel line between files so we can split the output.
            # grep -m2 limits lines per file to avoid huge outputs.
            parts = []
            for p in paths:
                parts.append(
                    f'echo "===FILE:{p}"; '
                    f'grep -m3 -E "^(- name:|  name:|  tags:|  description:)" '
                    f'{_q(p)} 2>/dev/null || true'
                )
            batch_cmd = "; ".join(parts)
            out2, _, _ = self._exec(client, batch_cmd, timeout=90)

            current_path: str | None = None
            meta: dict[str, dict] = {}

            for line in out2.splitlines():
                if line.startswith("===FILE:"):
                    current_path = line[8:].strip()
                    meta[current_path] = {"name": "", "tags": ""}
                elif current_path:
                    stripped = line.strip()
                    # Top-level playbook name: "- name: ..." or "name: ..."
                    if stripped.startswith("- name:") or stripped.startswith("name:"):
                        raw_name = stripped.split(":", 1)[-1].strip().strip("'\"")
                        if raw_name and not meta[current_path]["name"]:
                            meta[current_path]["name"] = raw_name
                    elif stripped.startswith("tags:"):
                        raw_tags = stripped.split(":", 1)[-1].strip()
                        meta[current_path]["tags"] = raw_tags

            playbooks = []
            for path in paths:
                filename = path.rsplit("/", 1)[-1]
                m = meta.get(path, {})
                display_name = m.get("name") or filename
                playbooks.append({
                    "name":        display_name,
                    "path":        path,
                    "description": display_name,
                    "tags":        m.get("tags", ""),
                })

            result["playbooks"] = playbooks
            result["count"]     = len(playbooks)

        except Exception as exc:
            logger.warning(
                "Ansible discover_playbooks unexpected error: %s", type(exc).__name__
            )
            result["errors"].append(
                f"An unexpected error occurred during playbook discovery "
                f"({type(exc).__name__}). Check the application logs."
            )
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass

        return result


# ── Shell quoting helper ──────────────────────────────────────────────────── #

def _q(path: str) -> str:
    """Shell-quote a path for use in remote commands (single-quotes)."""
    return "'" + path.replace("'", "'\\''") + "'"
