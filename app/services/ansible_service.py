"""
Ansible control node service — SSH-based connection validation,
inventory inspection, and playbook discovery.

This module only reads from the control node; it never executes
playbooks, modifies servers, or runs ad-hoc commands.

All SSH operations use paramiko. Credentials are never logged.
"""
from __future__ import annotations

import io
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Status strings that match CONNECTION_STATUS_OPTIONS in ansible_config.py
_STATUS_CONNECTED              = "Connected"
_STATUS_DISCONNECTED           = "Disconnected"
_STATUS_AUTH_FAILED            = "Authentication Failed"
_STATUS_HOST_KEY_MISMATCH      = "Host Key Mismatch"
_STATUS_INVENTORY_MISSING      = "Inventory Missing"
_STATUS_PLAYBOOK_DIR_MISSING   = "Playbook Directory Missing"
_STATUS_ANSIBLE_NOT_INSTALLED  = "Ansible Not Installed"
_STATUS_TIMEOUT                = "Connection Timeout"


class AnsibleConnectionError(Exception):
    """Raised when SSH connection or authentication fails."""
    def __init__(self, message: str, status: str = _STATUS_DISCONNECTED):
        super().__init__(message)
        self.status = status


class AnsibleService:
    """SSH-based interface to an Ansible control node."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        auth_method: str,          # "key" | "password"
        ssh_password: str = "",
        ssh_private_key: str = "",  # PEM text
        host_key_checking: bool = True,
        timeout: int = 30,
    ):
        self.host             = host
        self.port             = port
        self.username         = username
        self.auth_method      = auth_method
        self.ssh_password     = ssh_password
        self.ssh_private_key  = ssh_private_key
        self.host_key_checking = host_key_checking
        self.timeout          = timeout

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
        )

    # ── Connection ────────────────────────────────────────────────────────── #

    def _connect(self):
        """
        Open a paramiko SSH client to the control node.

        Returns a connected SSHClient.  Raises AnsibleConnectionError with a
        sanitised message on any failure — credentials are never included.
        """
        try:
            import paramiko  # type: ignore
        except ImportError:
            raise AnsibleConnectionError(
                "paramiko is not installed. Run: pip install paramiko",
                status=_STATUS_DISCONNECTED,
            )

        client = paramiko.SSHClient()
        if self.host_key_checking:
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict[str, Any] = {
            "hostname": self.host,
            "port":     self.port,
            "username": self.username,
            "timeout":  self.timeout,
            "banner_timeout": self.timeout,
            "auth_timeout":   self.timeout,
        }

        if self.auth_method == "key" and self.ssh_private_key:
            pkey = self._load_private_key(self.ssh_private_key)
            connect_kwargs["pkey"] = pkey
            connect_kwargs["look_for_keys"] = False
            connect_kwargs["allow_agent"]   = False
        elif self.auth_method == "password" and self.ssh_password:
            connect_kwargs["password"]      = self.ssh_password
            connect_kwargs["look_for_keys"] = False
            connect_kwargs["allow_agent"]   = False
        else:
            # Try SSH agent / default key locations as last resort
            connect_kwargs["look_for_keys"] = True
            connect_kwargs["allow_agent"]   = True

        try:
            client.connect(**connect_kwargs)
            return client
        except Exception as exc:
            client.close()
            msg = str(exc).lower()
            if any(k in msg for k in ("authentication", "auth", "denied", "invalid key", "no auth")):
                raise AnsibleConnectionError(
                    f"Authentication Failed: Could not authenticate to {self.host}:{self.port}",
                    status=_STATUS_AUTH_FAILED,
                )
            if "not in known" in msg or "host key" in msg or "changed" in msg:
                raise AnsibleConnectionError(
                    f"Host Key Mismatch: The host key for {self.host} has changed or is not trusted.",
                    status=_STATUS_HOST_KEY_MISMATCH,
                )
            if any(k in msg for k in ("timeout", "timed out", "connection refused", "no route")):
                raise AnsibleConnectionError(
                    f"Connection Timeout: Could not reach {self.host}:{self.port}",
                    status=_STATUS_TIMEOUT,
                )
            raise AnsibleConnectionError(
                f"Disconnected: Could not connect to {self.host}:{self.port}",
                status=_STATUS_DISCONNECTED,
            )

    @staticmethod
    def _load_private_key(key_text: str):
        """Try to load a PEM private key (RSA, Ed25519, ECDSA, DSS)."""
        import paramiko  # type: ignore

        key_io = io.StringIO(key_text)
        for cls in (
            paramiko.RSAKey,
            paramiko.Ed25519Key,
            paramiko.ECDSAKey,
            paramiko.DSSKey,
        ):
            key_io.seek(0)
            try:
                return cls.from_private_key(key_io)
            except Exception:
                continue
        raise AnsibleConnectionError(
            "Could not load the SSH private key. "
            "Supported formats: RSA, Ed25519, ECDSA, DSS.",
            status=_STATUS_AUTH_FAILED,
        )

    @staticmethod
    def _exec(client, command: str, timeout: int = 60) -> tuple[str, str, int]:
        """Run a command and return (stdout, stderr, exit_code)."""
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

        Returns a dict with keys:
          success      bool
          status       str  (matches CONNECTION_STATUS_OPTIONS)
          message      str  (human-readable summary)
          ansible_version str | None
          python_version  str | None
          inventory_ok    bool
          playbook_dir_ok bool
          checks          list[dict]  — per-check detail rows for the UI
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

        client = None
        try:
            client = self._connect()
            result["checks"].append({"label": "SSH Connection", "ok": True,
                                     "detail": f"{self.host}:{self.port}"})
        except AnsibleConnectionError as exc:
            result["status"]  = exc.status
            result["message"] = str(exc)
            result["checks"].append({"label": "SSH Connection", "ok": False,
                                     "detail": str(exc)})
            return result

        try:
            # ── Ansible version ────────────────────────────────────────────── #
            out, _, code = self._exec(client, "ansible --version 2>&1 | head -4")
            if code != 0 or "ansible" not in out.lower():
                # Try with common path
                out2, _, code2 = self._exec(
                    client, "/usr/bin/ansible --version 2>&1 | head -4"
                )
                if code2 != 0 or "ansible" not in out2.lower():
                    result["status"]  = _STATUS_ANSIBLE_NOT_INSTALLED
                    result["message"] = "Ansible is not installed on the control node."
                    result["checks"].append({
                        "label": "Ansible Installed", "ok": False,
                        "detail": "ansible not found in PATH"
                    })
                    return result
                out = out2

            # Parse version line: "ansible [core 2.15.0]" or "ansible 2.9.x"
            version_line = out.splitlines()[0] if out.splitlines() else ""
            m = re.search(r"(\d+\.\d+[\.\d]*)", version_line)
            ansible_ver = m.group(1) if m else version_line.strip()
            result["ansible_version"] = ansible_ver
            result["checks"].append({
                "label": "Ansible Version", "ok": True, "detail": version_line.strip()
            })

            # ── ansible-playbook ──────────────────────────────────────────── #
            out2, _, code2 = self._exec(
                client, "ansible-playbook --version 2>&1 | head -1"
            )
            pb_ok = code2 == 0 and "ansible-playbook" in out2.lower()
            result["checks"].append({
                "label": "ansible-playbook",
                "ok":    pb_ok,
                "detail": out2.strip()[:80] if pb_ok else "Not found",
            })

            # ── Python version ─────────────────────────────────────────────── #
            out3, _, _ = self._exec(
                client,
                "python3 --version 2>&1 || python --version 2>&1"
            )
            py_line = out3.strip().splitlines()[0] if out3.strip() else ""
            py_ok = bool(py_line)
            result["python_version"] = py_line
            result["checks"].append({
                "label": "Python", "ok": py_ok,
                "detail": py_line or "Not found",
            })

            # ── Inventory path ─────────────────────────────────────────────── #
            inv_path = self._inventory_path_arg()
            out4, _, code4 = self._exec(
                client,
                f'test -e {_q(inv_path)} && echo OK || echo MISSING'
            )
            inv_ok = "OK" in out4
            result["inventory_ok"] = inv_ok
            if not inv_ok:
                result["status"]  = _STATUS_INVENTORY_MISSING
                result["message"] = f"Inventory path not found: {inv_path}"
            result["checks"].append({
                "label": f"Inventory ({inv_path})",
                "ok":    inv_ok,
                "detail": "Exists" if inv_ok else f"Not found: {inv_path}",
            })

            # ── Playbook directory ─────────────────────────────────────────── #
            out5, _, code5 = self._exec(
                client,
                f'test -d {_q(self._playbook_dir)} && echo OK || echo MISSING'
            )
            pb_dir_ok = "OK" in out5
            result["playbook_dir_ok"] = pb_dir_ok
            if not pb_dir_ok and inv_ok:
                result["status"]  = _STATUS_PLAYBOOK_DIR_MISSING
                result["message"] = f"Playbook directory not found: {self._playbook_dir}"
            result["checks"].append({
                "label": f"Playbook Directory ({self._playbook_dir})",
                "ok":    pb_dir_ok,
                "detail": "Exists" if pb_dir_ok else f"Not found: {self._playbook_dir}",
            })

            # ── Final status ───────────────────────────────────────────────── #
            if inv_ok:   # inventory is the hard requirement
                result["success"] = True
                result["status"]  = _STATUS_CONNECTED
                result["message"] = (
                    f"Connected — Ansible {ansible_ver or ''} "
                    f"on {self.host}:{self.port}"
                )

        except Exception as exc:
            logger.warning("Ansible test_connection error: %s", exc)
            result["message"] = f"Unexpected error during connection test: {type(exc).__name__}"
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

        Returns:
          success       bool
          host_count    int
          group_names   list[str]
          hosts         list[str]  — unique hostnames/IPs
          errors        list[str]
          raw_groups    dict       — group → hosts mapping
        """
        result: dict[str, Any] = {
            "success":    False,
            "host_count": 0,
            "group_names": [],
            "hosts":      [],
            "errors":     [],
            "raw_groups": {},
        }

        client = None
        try:
            client = self._connect()
        except AnsibleConnectionError as exc:
            result["errors"].append(str(exc))
            return result

        try:
            inv_path = self._inventory_path_arg()
            cmd = f"ansible-inventory -i {_q(inv_path)} --list 2>&1"
            out, _, _ = self._exec(client, cmd, timeout=60)

            # ansible-inventory --list outputs JSON, possibly with warning lines first
            json_start = out.find("{")
            if json_start == -1:
                result["errors"].append(
                    "Could not parse inventory output — no JSON found. "
                    "Check that ansible-inventory is installed and the inventory path is correct."
                )
                return result

            prefix = out[:json_start].strip()
            if prefix:
                for line in prefix.splitlines():
                    if line.strip():
                        result["errors"].append(f"Warning: {line.strip()}")

            try:
                data = json.loads(out[json_start:])
            except json.JSONDecodeError as exc:
                result["errors"].append(f"Inventory JSON parse error: {exc}")
                return result

            # All unique hostnames live in _meta.hostvars
            hostvars = data.get("_meta", {}).get("hostvars", {})
            hosts = sorted(hostvars.keys())
            result["hosts"]      = hosts
            result["host_count"] = len(hosts)

            # Group names are top-level keys except _meta and all
            groups: dict[str, list[str]] = {}
            for key, val in data.items():
                if key in ("_meta", "all"):
                    continue
                if isinstance(val, dict):
                    group_hosts = val.get("hosts", [])
                    if not group_hosts:
                        # Children array — skip, or flatten
                        continue
                    groups[key] = group_hosts

            result["group_names"] = sorted(groups.keys())
            result["raw_groups"]  = groups
            result["success"]     = True

        except Exception as exc:
            logger.warning("Ansible validate_inventory error: %s", exc)
            result["errors"].append(f"Error during inventory validation: {type(exc).__name__}: {exc}")
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass

        return result

    # ── Playbook discovery ────────────────────────────────────────────────── #

    def discover_playbooks(self) -> list[dict[str, str]]:
        """
        Find YAML playbooks in the configured playbook directory.

        Returns a list of dicts:
          name        str  (from the first 'name:' key in the file, or filename)
          path        str  (full path on control node)
          description str  (same as name — Ansible has no description field)
          tags        str  (comma-joined tag list if found, else "")
        """
        playbooks: list[dict[str, str]] = []
        client = None
        try:
            client = self._connect()
        except AnsibleConnectionError as exc:
            logger.warning("Ansible discover_playbooks connect failed: %s", exc)
            return playbooks

        try:
            # ── Discover YAML files ───────────────────────────────────────── #
            find_cmd = (
                f"find {_q(self._playbook_dir)} -maxdepth 3 "
                r"\( -name '*.yml' -o -name '*.yaml' \) "
                r"! -name '*.vault.yml' ! -name '*.vault.yaml' "
                r"-type f 2>/dev/null | sort | head -100"
            )
            out, _, _ = self._exec(client, find_cmd, timeout=30)
            paths = [p.strip() for p in out.splitlines() if p.strip()]

            if not paths:
                return playbooks

            # ── Read name/tags from each file (one batched command) ───────── #
            # Emit a sentinel line between files for easy parsing
            parts = []
            for p in paths:
                parts.append(
                    f'echo "===FILE:{p}"; '
                    f'grep -m2 -E "^(- name:|  name:|  tags:)" {_q(p)} 2>/dev/null || true'
                )
            batch_cmd = "; ".join(parts)
            out2, _, _ = self._exec(client, batch_cmd, timeout=60)

            current_path = None
            meta: dict[str, dict] = {}  # path → {name, tags}

            for line in out2.splitlines():
                if line.startswith("===FILE:"):
                    current_path = line[8:].strip()
                    meta[current_path] = {"name": "", "tags": ""}
                elif current_path:
                    stripped = line.strip()
                    if stripped.startswith("- name:") or stripped.startswith("name:"):
                        raw_name = stripped.split(":", 1)[-1].strip().strip("'\"")
                        if raw_name and not meta[current_path]["name"]:
                            meta[current_path]["name"] = raw_name
                    elif stripped.startswith("tags:"):
                        raw_tags = stripped.split(":", 1)[-1].strip()
                        meta[current_path]["tags"] = raw_tags

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

        except Exception as exc:
            logger.warning("Ansible discover_playbooks error: %s", exc)
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass

        return playbooks

    # ── Internal helpers ──────────────────────────────────────────────────── #

    def _inventory_path_arg(self) -> str:
        """Return the raw inventory path string."""
        return self._inventory_path if hasattr(self, "_inventory_path") else "/etc/ansible/hosts"

    @property
    def _playbook_dir(self) -> str:
        return getattr(self, "__playbook_dir", "/etc/ansible/playbooks")

    def __init__(self, host, port, username, auth_method, ssh_password="",
                 ssh_private_key="", host_key_checking=True, timeout=30,
                 inventory_path="/etc/ansible/hosts",
                 playbook_dir="/etc/ansible/playbooks"):
        self.host             = host
        self.port             = port
        self.username         = username
        self.auth_method      = auth_method
        self.ssh_password     = ssh_password
        self.ssh_private_key  = ssh_private_key
        self.host_key_checking = host_key_checking
        self.timeout          = timeout
        self._inventory_path  = inventory_path
        self.__playbook_dir   = playbook_dir

    @classmethod
    def from_config(cls, cfg) -> "AnsibleService":
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


def _q(path: str) -> str:
    """Shell-quote a path for use in remote commands (single-quotes)."""
    return "'" + path.replace("'", "'\\''") + "'"
