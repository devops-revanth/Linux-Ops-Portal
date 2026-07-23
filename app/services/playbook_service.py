"""
Playbook execution service — Phase 3.

Orchestrates all interactions with the remote Ansible control node:
  • Catalog discovery  — find and parse playbooks (read-only, never executes)
  • Job execution      — build command, SSH exec, stream output to DB
  • Job cancellation   — SIGTERM the remote ansible-playbook process
  • Statistics parsing — extract PLAY RECAP counts from log output

Security rules:
  - Never log SSH passwords, private keys, or vault passwords
  - Sanitize all output before surfacing to UI (no internal paths in errors)
  - All execution on the remote Ansible control node only
"""
from __future__ import annotations

import logging
import re
import shlex
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ANSI escape-code stripper
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mGKHF]")

# PLAY RECAP stats line:  "hostname : ok=3 changed=1 unreachable=0 failed=0"
_RECAP_RE = re.compile(
    r"(\S+)\s*:\s*ok=(\d+)\s+changed=(\d+)\s+unreachable=(\d+)\s+failed=(\d+)"
    r"(?:\s+skipped=(\d+))?",
    re.IGNORECASE,
)

# Map of known error patterns → safe user-facing messages
_ERROR_MAP = [
    ("Permission denied",    "SSH permission denied"),
    ("Authentication failed","SSH authentication failed"),
    ("timed out",            "Connection timed out"),
    ("Connection refused",   "Connection refused"),
    ("No route to host",     "Host unreachable"),
    ("unreachable",          "Host unreachable"),
    ("No such file",         "Playbook file not found on control node"),
    ("command not found",    "ansible-playbook not found on control node"),
]


def _sanitize_error(exc) -> str:
    msg = str(exc) if exc else ""
    for marker, friendly in _ERROR_MAP:
        if marker.lower() in msg.lower():
            return friendly
    first = msg.splitlines()[0] if msg else "Unknown error"
    return first[:200]


def _q(s: str) -> str:
    """POSIX single-quote a string for safe shell embedding."""
    return "'" + s.replace("'", "'\\''") + "'"


# ── Playbook discovery ─────────────────────────────────────────────────────── #

def discover_playbooks(cfg, app) -> dict[str, Any]:
    """
    SSH to the configured control node, find *.yml / *.yaml files under the
    configured playbook directory, and upsert catalog records in the DB.

    Never executes any playbook — read-only filesystem traversal only.

    Returns a summary dict: {found, new, updated, errors}.
    """
    from ..models.playbook import Playbook
    from ..extensions import db
    from ..services.ansible_service import AnsibleService

    summary = {"found": 0, "new": 0, "updated": 0, "errors": []}

    pb_dir     = (cfg.playbook_dir or "/etc/ansible/playbooks").rstrip("/")
    ssh_target = f"{cfg.username or '?'}@{cfg.control_node or '?'}:{cfg.port or 22}"

    logger.info(
        "Playbook discovery starting:\n"
        "  Playbook Directory : %s\n"
        "  SSH Target         : %s",
        pb_dir, ssh_target,
    )

    # ── SSH connection ──────────────────────────────────────────────────────
    try:
        svc    = AnsibleService.from_config(cfg)
        client = svc._connect()
    except Exception as exc:
        err = _sanitize_error(exc)
        logger.error(
            "Playbook discovery: SSH connection failed — %s: %s",
            type(exc).__name__, exc,
        )
        summary["errors"].append(err)
        return summary

    try:
        # ── Find command ────────────────────────────────────────────────────
        # Recursive, no depth limit.  Excludes non-playbook trees.
        # -printf '%P\t%T@\n' gives path-relative-to-start-point TAB mtime.
        cmd = (
            f"find {_q(pb_dir)}"
            f" -type f"
            f" \\( -name '*.yml' -o -name '*.yaml' \\)"
            f" ! -path '*/roles/*'"
            f" ! -path '*/collections/*'"
            f" ! -path '*/.git/*'"
            f" ! -path '*/__pycache__/*'"
            f" -printf '%P\\t%T@\\n'"
            f" 2>/dev/null | sort"
        )
        logger.debug("Playbook discovery: command: %s", cmd)

        stdout, stderr, rc = AnsibleService._exec(client, cmd, timeout=60)

        logger.info(
            "Playbook discovery find result:\n"
            "  Command    : %s\n"
            "  Exit code  : %d\n"
            "  Stderr     : %s\n"
            "  Lines out  : %d\n"
            "  Stdout     : %s",
            cmd, rc,
            stderr.strip()[:400] if stderr.strip() else "(none)",
            len(stdout.splitlines()),
            stdout[:800] if stdout else "(empty)",
        )

        if not stdout.strip():
            msg = (
                f"No playbooks found under {pb_dir}. "
                f"Verify the directory exists on the control node and contains "
                f"*.yml / *.yaml files."
            )
            logger.warning("Playbook discovery: %s", msg)
            summary["errors"].append(msg)
            return summary

        # ── Parse find output and upsert each playbook ──────────────────────
        now = datetime.now(timezone.utc)
        for line in stdout.splitlines():
            if "\t" not in line:
                continue
            rel_path, mtime_str = line.split("\t", 1)
            rel_path = rel_path.strip()
            if not rel_path:
                continue
            summary["found"] += 1

            try:
                last_mod = datetime.fromtimestamp(float(mtime_str.strip()), tz=timezone.utc)
            except (ValueError, OSError):
                last_mod = None

            # Read first 50 lines for metadata (one SSH exec per file)
            abs_path = pb_dir + "/" + rel_path
            head_out, _, _ = AnsibleService._exec(
                client, f"head -50 {_q(abs_path)} 2>/dev/null", timeout=10
            )
            meta = parse_metadata(head_out, rel_path)

            with app.app_context():
                existing = Playbook.query.filter_by(relative_path=rel_path).first()
                if existing:
                    existing.name               = meta["name"]
                    existing.description        = meta["description"]
                    existing.category           = meta["category"]
                    existing.tags               = meta["tags"]
                    existing.requires_become    = meta["requires_become"]
                    existing.requires_variables = meta["requires_variables"]
                    existing.last_modified      = last_mod
                    existing.metadata_source    = meta["source"]
                    existing.discovered_at      = now
                    summary["updated"] += 1
                else:
                    pb = Playbook(
                        name               = meta["name"],
                        description        = meta["description"],
                        relative_path      = rel_path,
                        category           = meta["category"],
                        tags               = meta["tags"],
                        requires_become    = meta["requires_become"],
                        requires_variables = meta["requires_variables"],
                        last_modified      = last_mod,
                        is_enabled         = True,
                        is_internal        = rel_path.startswith(".") or "/_" in rel_path,
                        metadata_source    = meta["source"],
                        discovered_at      = now,
                    )
                    db.session.add(pb)
                    summary["new"] += 1
                db.session.commit()

        logger.info(
            "Playbook discovery complete: found=%d new=%d updated=%d errors=%d",
            summary["found"], summary["new"], summary["updated"], len(summary["errors"]),
        )

    except Exception as exc:
        logger.exception("Playbook discovery: unexpected error — %s", exc)
        summary["errors"].append(_sanitize_error(exc))
    finally:
        try:
            client.close()
        except Exception:
            pass

    return summary


def parse_metadata(content: str, relative_path: str) -> dict[str, Any]:
    """
    Extract playbook metadata from YAML comment headers.

    Recognizes lines of the form:
      # Name: My Playbook
      # Description: Does something useful
      # Category: Patching
      # Requires Become: true
      # Tags: security, updates
      # Requires Variables: reboot=true

    Falls back to filename-derived values when comments are absent.
    """
    meta: dict[str, Any] = {
        "name":               None,
        "description":        None,
        "category":           None,
        "tags":               None,
        "requires_become":    False,
        "requires_variables": None,
        "source":             "filename",
    }
    found_any = False

    for line in content.splitlines()[:50]:
        line = line.strip()
        if not line.startswith("#"):
            if line and not line.startswith("---") and not line.startswith("#"):
                break   # Stop at first non-comment, non-separator line
            continue
        body = line[1:].strip()
        if ":" not in body:
            continue
        key, _, val = body.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if not val:
            continue

        found_any = True
        if key == "name":
            meta["name"] = val
        elif key == "description":
            meta["description"] = val
        elif key in ("category", "type"):
            meta["category"] = val
        elif key in ("tags", "default tags"):
            meta["tags"] = val
        elif key in ("requires become", "become"):
            meta["requires_become"] = val.lower() in ("true", "yes", "1")
        elif key in ("requires variables", "variables"):
            meta["requires_variables"] = val

    if found_any:
        meta["source"] = "comment"

    # Fallback: derive name from filename
    if not meta["name"]:
        filename = relative_path.rsplit("/", 1)[-1]
        stem = filename.rsplit(".", 1)[0]
        meta["name"] = stem.replace("_", " ").replace("-", " ").title()

    return meta


# ── Command construction ──────────────────────────────────────────────────── #

def build_ansible_command(job, cfg) -> str:
    """
    Build a safe ansible-playbook command string for a PlaybookJob.

    Uses the full absolute path on the control node.
    Never embeds SSH credentials in the command.
    """
    pb_dir   = (cfg.playbook_dir or "/etc/ansible/playbooks").rstrip("/")
    pb_path  = pb_dir + "/" + job.playbook_path.lstrip("/")

    parts = ["ansible-playbook", _q(pb_path)]

    # Inventory
    if job.inventory_type == "file" and job.inventory_value:
        parts += ["-i", _q(job.inventory_value)]
    elif job.inventory_type == "dynamic" and job.inventory_value:
        parts += ["-i", _q(job.inventory_value)]
    # else: rely on ansible.cfg / system default

    # Host limiting
    if job.limit_expression:
        parts += ["--limit", _q(job.limit_expression)]

    # Execution flags
    if job.become:
        parts.append("--become")
    if job.check_mode:
        parts.append("--check")
    if job.diff_mode:
        parts.append("--diff")
    if job.forks and job.forks != 5:
        parts += ["--forks", str(int(job.forks))]

    verbosity_flag = {1: "-v", 2: "-vv", 3: "-vvv", 4: "-vvvv"}.get(int(job.verbosity or 0))
    if verbosity_flag:
        parts.append(verbosity_flag)

    if job.tags:
        parts += ["--tags", _q(job.tags)]
    if job.skip_tags:
        parts += ["--skip-tags", _q(job.skip_tags)]

    if job.extra_vars:
        ev = job.extra_vars.strip()
        if ev:
            parts += ["--extra-vars", _q(ev)]

    return " ".join(parts)


# ── Job execution ──────────────────────────────────────────────────────────── #

def launch_job(job_id: int, app) -> None:
    """
    Execute a playbook job on the remote Ansible control node.

    Designed to run in a daemon thread — never called from a request context.
    Streams output to the DB as it arrives. Updates job status on completion.
    """
    from ..models.playbook import PlaybookJob
    from ..models.ansible_config import AnsibleConfig
    from ..services.ansible_service import AnsibleService
    from ..extensions import db
    from ..audit import log_action

    with app.app_context():
        job = PlaybookJob.query.get(job_id)
        if job is None:
            return
        if job.status == "cancelled":
            return

        cfg = AnsibleConfig.query.first()
        if cfg is None:
            _fail_job(job, "No Ansible configuration found")
            return

        # Mark running
        job.status     = "running"
        job.started_at = datetime.now(timezone.utc)
        db.session.commit()

        log_action(
            "playbook.job.start",
            target     = job.playbook_name or job.playbook_path,
            details    = f"job_id={job.id} limit={job.limit_expression!r}",
            result     = "success",
        )
        db.session.commit()

        client = None
        try:
            svc    = AnsibleService.from_config(cfg)
            client = svc._connect()

            cmd = build_ansible_command(job, cfg)
            # Wrap to expose the shell PID before exec-ing ansible-playbook
            wrapped = f"bash -c 'echo \"LOP_PID:$$\"; exec {cmd}'"

            transport = client.get_transport()
            channel   = transport.open_session()
            channel.get_pty(term="xterm-256color", width=220, height=50)
            channel.set_combine_stderr(True)

            # Set ANSIBLE_FORCE_COLOR so output is colorized (stripped for plain display)
            env_prefix = "ANSIBLE_FORCE_COLOR=1 "
            channel.exec_command(env_prefix + wrapped)

            pid_captured = False
            buf: list[str] = []
            last_flush    = time.monotonic()

            while True:
                # Re-check for cancellation every iteration
                db.session.expire(job)
                if job.status == "cancelled":
                    try: channel.close()
                    except Exception: pass
                    break

                if channel.recv_ready():
                    raw  = channel.recv(8192)
                    if raw:
                        text = raw.decode("utf-8", errors="replace")

                        # Capture PID from first wrapped line
                        if not pid_captured and "LOP_PID:" in text:
                            lines = text.splitlines(keepends=True)
                            filtered = []
                            for ln in lines:
                                if ln.strip().startswith("LOP_PID:"):
                                    try:
                                        job.remote_pid = int(ln.split(":")[1].strip())
                                        db.session.commit()
                                    except (ValueError, IndexError):
                                        pass
                                else:
                                    filtered.append(ln)
                            text = "".join(filtered)
                            pid_captured = True

                        buf.append(text)

                if channel.exit_status_ready() and not channel.recv_ready():
                    break

                # Flush buffer to DB every 2 seconds or 32 KB
                elapsed = time.monotonic() - last_flush
                if buf and (elapsed >= 2.0 or sum(len(x) for x in buf) > 32768):
                    _append_log(job.id, "".join(buf), app)
                    buf.clear()
                    last_flush = time.monotonic()

                time.sleep(0.1)

            # Drain any remaining output
            while channel.recv_ready():
                raw = channel.recv(8192)
                if raw:
                    buf.append(raw.decode("utf-8", errors="replace"))

            if buf:
                _append_log(job.id, "".join(buf), app)

            if job.status == "cancelled":
                return

            exit_code = channel.recv_exit_status()

        except Exception as exc:
            err = _sanitize_error(exc)
            logger.warning("Job %d execution error: %s", job_id, err)
            with app.app_context():
                job2 = PlaybookJob.query.get(job_id)
                if job2:
                    job2.status       = "failed"
                    job2.error_message = err
                    job2.finished_at  = datetime.now(timezone.utc)
                    db.session.commit()
            return
        finally:
            try:
                if client: client.close()
            except Exception:
                pass

        # Finalise
        with app.app_context():
            job2 = PlaybookJob.query.get(job_id)
            if job2 and job2.status != "cancelled":
                job2.exit_code   = exit_code
                job2.status      = "completed" if exit_code == 0 else "failed"
                job2.finished_at = datetime.now(timezone.utc)
                _parse_job_stats(job2)
                db.session.commit()
                log_action(
                    f"playbook.job.{'complete' if exit_code == 0 else 'fail'}",
                    target  = job2.playbook_name or job2.playbook_path,
                    details = (
                        f"job_id={job2.id} exit_code={exit_code} "
                        f"ok={job2.hosts_ok} failed={job2.hosts_failed} "
                        f"duration={job2.duration_seconds}s"
                    ),
                    result  = "success" if exit_code == 0 else "failure",
                )
                db.session.commit()


def _append_log(job_id: int, chunk: str, app) -> None:
    """Append a text chunk to the job's log_output using SQL concatenation."""
    from sqlalchemy import text
    from ..extensions import db

    with app.app_context():
        db.session.execute(
            text(
                "UPDATE playbook_jobs "
                "SET log_output = COALESCE(log_output, '') || :chunk, "
                "    log_size   = COALESCE(log_size, 0) + :sz "
                "WHERE id = :id"
            ),
            {"chunk": chunk, "sz": len(chunk), "id": job_id},
        )
        db.session.commit()


def _fail_job(job, message: str) -> None:
    from ..extensions import db
    job.status        = "failed"
    job.error_message = message
    job.finished_at   = datetime.now(timezone.utc)
    db.session.commit()


def _parse_job_stats(job) -> None:
    """
    Parse the PLAY RECAP block in the job log to extract per-host statistics.
    Aggregates across all hosts.
    """
    output = job.log_output or ""
    ok = changed = failed = skipped = unreachable = 0
    hosts_seen = set()
    for m in _RECAP_RE.finditer(output):
        host = m.group(1)
        if host in hosts_seen:
            continue
        hosts_seen.add(host)
        ok          += int(m.group(2))
        changed     += int(m.group(3))
        unreachable += int(m.group(4))
        failed      += int(m.group(5))
        skipped     += int(m.group(6) or 0)

    if hosts_seen:
        job.hosts_ok          = ok
        job.hosts_changed     = changed
        job.hosts_failed      = failed
        job.hosts_skipped     = skipped
        job.hosts_unreachable = unreachable
        # Count TASK lines for task_count
        job.task_count = len(re.findall(r"^TASK\s*\[", output, re.MULTILINE))


# ── Job cancellation ──────────────────────────────────────────────────────── #

def cancel_job(job_id: int, app) -> bool:
    """
    Attempt to cancel a running job by sending SIGTERM to the remote process.

    Returns True if the cancel signal was sent, False otherwise.
    """
    from ..models.playbook import PlaybookJob
    from ..models.ansible_config import AnsibleConfig
    from ..services.ansible_service import AnsibleService
    from ..extensions import db

    with app.app_context():
        job = PlaybookJob.query.get(job_id)
        if job is None or job.status not in ("pending", "running"):
            return False

        # Mark cancelled immediately so the launch thread stops reading
        job.status      = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        db.session.commit()

        if job.remote_pid:
            cfg = AnsibleConfig.query.first()
            if cfg:
                try:
                    svc    = AnsibleService.from_config(cfg)
                    client = svc._connect()
                    # Kill the process group to catch child ansible forks
                    AnsibleService._exec(
                        client,
                        f"kill -SIGTERM {job.remote_pid} 2>/dev/null; "
                        f"kill -SIGTERM -- -{job.remote_pid} 2>/dev/null || true",
                        timeout=10,
                    )
                    client.close()
                except Exception as exc:
                    logger.debug("Cancel signal failed: %s", _sanitize_error(exc))

        return True


# ── ANSI stripping ─────────────────────────────────────────────────────────── #

def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from a string."""
    return _ANSI_RE.sub("", text)
