from __future__ import annotations

import copy
import difflib
import fcntl
import hashlib
import json
import os
import re
import secrets
import shlex
import socket
import subprocess
import tomllib
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent_team.diagnostics import Diagnostic, ValidationFailure
from agent_team.fs import atomic_write
from agent_team.models import TeamConfig
from agent_team.recovery import discover_runs, fingerprint_workspace, select_run
from agent_team.runs import utc_now, validate_run
from agent_team.toml_edit import _layout, _same_values, _statements


def fail(message: str) -> None:
    raise ValidationFailure([Diagnostic("run state", message, code="state")])


def literal(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).replace("\u007f", "\\u007f")
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(literal(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {literal(v)}" for k, v in value.items()) + " }"
    fail("unsupported state value")
    raise AssertionError


def edit_scalars(content: str, changes: dict[tuple[str, ...], Any]) -> str:
    expected = copy.deepcopy(tomllib.loads(content))
    _, assignments = _layout(content)
    edits = []
    for path, value in changes.items():
        parent = expected
        for part in path[:-1]:
            parent = parent[part]
        parent[path[-1]] = value
        matches = [a for a in assignments if a.path == path and len(a.key) == 1]
        if len(matches) != 1:
            fail("cannot safely locate scalar; expand inline or dotted table first")
        assignment = matches[0]
        original = content[assignment.value_start:assignment.statement_end]
        # These edits only target ordinary single-line strings, integers and booleans.
        match = re.match(r'''(?:"(?:[^"\\\n]|\\.)*"|'[^'\n]*'|true|false|[+-]?[0-9_]+)(?=\s*(?:#|$))''', original)
        if match is None:
            fail("unsupported scalar layout")
        edits.append((assignment.value_start, assignment.value_start + match.end(), literal(value)))
    for start, end, replacement in sorted(edits, reverse=True):
        content = content[:start] + replacement + content[end:]
    if not _same_values(tomllib.loads(content), expected):
        fail("scalar edit changed unrelated values")
    return content


def edit_lease(content: str, task_id: str, lease: dict | None) -> str:
    original = tomllib.loads(content)
    expected = copy.deepcopy(original)
    indices = [i for i, t in enumerate(original.get("tasks", [])) if t.get("id") == task_id]
    if len(indices) != 1:
        fail("task must exist exactly once")
    index = indices[0]
    task = expected["tasks"][index]
    if lease is None:
        task.pop("lease", None)
    else:
        task["lease"] = lease
    spans = _statements(content)
    headers = [(start, end) for start, end in spans
               if content[start:end].strip().split("#", 1)[0].strip() == "[[tasks]]"]
    if len(headers) != len(original["tasks"]):
        fail("unsupported tasks layout; use ordinary [[tasks]] headers")
    _, header_end = headers[index]
    end = len(content)
    for left, right in spans:
        if left >= header_end and content[left:right].lstrip().startswith("["):
            end = left
            break
    block = content[header_end:end]
    lease_spans = [(a, b) for a, b in _statements(block)
                   if block[a:b].lstrip().startswith("lease")
                   and block[a:b].lstrip()[5:].lstrip().startswith("=")]
    if len(lease_spans) > 1:
        fail("ambiguous lease layout")
    if lease_spans:
        left, right = lease_spans[0]
        block = block[:left] + block[right:]
    if lease is not None:
        block = f"lease = {literal(lease)}\n" + block
    result = content[:header_end] + block + content[end:]
    if not _same_values(tomllib.loads(result), expected):
        fail("unsupported lease layout; expand lease as a single inline assignment")
    return result


@contextmanager
def locked_run(root: Path, config: TeamConfig, slug: str):
    candidate, _ = select_run(discover_runs(root, config), root, slug=slug)
    if candidate is None or candidate.errors:
        fail("run cannot be read safely")
    lock = root / ".agent-team" / "state.lock"
    if lock.is_symlink() or not lock.resolve().is_relative_to(root.resolve()):
        fail("state lock escapes project")
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        content = candidate.path.read_text(encoding="utf-8")
        yield candidate.path, content


def save(path: Path, before: str, after: str) -> None:
    if path.read_text(encoding="utf-8") != before:
        fail("manifest changed during update; retry after reconciliation")
    atomic_write(path, after)


def lease_change(root: Path, config: TeamConfig, slug: str, task_id: str,
                 *, owner: str | None = None, owned_paths: list[str] | None = None,
                 token: str | None = None) -> str:
    with locked_run(root, config, slug) as (path, content):
        data = tomllib.loads(content)
        tasks = [t for t in data.get("tasks", []) if t.get("id") == task_id]
        if len(tasks) != 1:
            fail("task not found or duplicated")
        task = tasks[0]
        if token is not None:
            lease = task.get("lease")
            if not isinstance(lease, dict) or not secrets.compare_digest(str(lease.get("token", "")), token):
                fail("lease token mismatch")
            after = edit_lease(content, task_id, None)
            result = "released"
        else:
            if task.get("status") != "running" or task.get("lease") is not None:
                fail("claim requires a running task with no existing lease")
            if data.get("gates", {}).get("worker_closure") is True:
                fail("reopen worker_closure before claiming")
            if not owner or not owner.strip() or not owned_paths:
                fail("owner and owned paths are required")
            for owned in owned_paths:
                p = Path(owned)
                if not owned or p.is_absolute() or ".." in p.parts or not (root / p).resolve().is_relative_to(root.resolve()):
                    fail("owned path must remain in project")
            for other in data.get("tasks", []):
                if other is task or other.get("status") != "running":
                    continue
                other_lease = other.get("lease")
                if not isinstance(other_lease, dict) or not other_lease.get("owned_paths"):
                    fail("another running task has unknown ownership; reconcile before claiming")
                for claimed in owned_paths:
                    for occupied in other_lease["owned_paths"]:
                        left, right = (root / claimed).resolve(), (root / occupied).resolve()
                        if left.is_relative_to(right) or right.is_relative_to(left):
                            fail("owned paths overlap another running task")
            result = secrets.token_hex(16)
            now = utc_now()
            after = edit_lease(content, task_id, {"owner": owner, "host": socket.gethostname(),
                "claimed_at": now, "last_observed_at": now, "token": result, "owned_paths": owned_paths})
        save(path, content, after)
        return result


def known(identity: dict[str, str]) -> bool:
    return all(value not in {"unknown", "dirty-unbounded"} for value in identity.values())


def verify(root: Path, config: TeamConfig, slug: str, command: list[str], producer: str,
           cwd: str = ".") -> int:
    candidate, _ = select_run(discover_runs(root, config), root, slug=slug)
    if candidate is None or candidate.errors:
        fail("verification requires a readable run")
    directory = (root / cwd).resolve()
    if Path(cwd).is_absolute() or ".." in Path(cwd).parts or not directory.is_relative_to(root.resolve()):
        fail("check cwd must remain in project")
    if not command or not producer.strip():
        fail("check command and producer are required")
    before = asdict(fingerprint_workspace(root))
    try:
        result = subprocess.run(command, cwd=directory, check=False)
        exit_status = result.returncode
    except OSError:
        exit_status = 127
    after = asdict(fingerprint_workspace(root))
    identity = before if before == after and known(before) else {
        "revision": "unknown", "tracked_diff_sha256": "unknown", "untracked_sha256": "unknown"}
    record = {"command": shlex.join(command), "cwd": directory.relative_to(root.resolve()).as_posix(),
              "exit_status": exit_status, **identity, "producer": producer, "at": utc_now()}
    with locked_run(root, config, slug) as (path, content):
        updated = content.rstrip() + "\n\n[[verification]]\n" + "".join(
            f"{key} = {literal(value)}\n" for key, value in record.items())
        parsed = tomllib.loads(content)
        parsed.setdefault("verification", []).append(record)
        if not _same_values(tomllib.loads(updated), parsed):
            fail("verification append changed unrelated values")
        save(path, content, updated)
    return exit_status if exit_status >= 0 else 1


def bind(root: Path, config: TeamConfig, slug: str, session_id: str | None) -> Path:
    selected, _ = select_run(discover_runs(root, config), root, slug=slug)
    if selected is None or selected.errors or not selected.active:
        fail("bind requires a readable active run")
    session_id = session_id or os.environ.get("AGENT_TEAM_SESSION_ID")
    digest = hashlib.sha256(session_id.encode()).hexdigest()[:16] if session_id else None
    path = root / ".agent-team" / "sessions" / (digest + ".json" if digest else "current.json")
    if not path.resolve().is_relative_to(root.resolve()):
        fail("session pointer escapes project")
    atomic_write(path, json.dumps({"session_id_hash": digest, "run_slug": slug,
        "run_path": selected.path.parent.relative_to(root).as_posix(), "project_root": str(root.resolve()),
        "updated_at": utc_now(), "baseline_revision": selected.manifest.get("git", {}).get("baseline_revision", "unknown")}, indent=2) + "\n")
    return path


def reconcile(root: Path, config: TeamConfig, slug: str, apply: bool) -> str:
    with locked_run(root, config, slug) as (path, content):
        data = tomllib.loads(content)
        tier = config.tiers.get(data.get("tier"))
        if tier is None:
            fail("unknown tier")
        changes = {("max_workers",): tier.max_workers, ("write_isolation",): tier.write_isolation,
            ("reports_required",): data["tier"] == "team" or (
                data["tier"] == "assisted" and config.workflow.persist_agent_reports),
            ("review", "required"): tier.independent_review,
            ("review", "limit"): config.workflow.review_cycle_limit}
        updated = edit_scalars(content, changes)
        # Validate against the original artifact directory without changing run.toml.
        temporary = path.parent / (".reconcile-" + secrets.token_hex(8) + ".toml")
        try:
            atomic_write(temporary, updated)
            errors = [d for d in validate_run(temporary, config) if d.severity == "error"]
            if errors:
                raise ValidationFailure(errors)
        finally:
            temporary.unlink(missing_ok=True)
        diff = "".join(difflib.unified_diff(content.splitlines(True), updated.splitlines(True),
                                             fromfile="run.toml", tofile="run.toml (reconciled)"))
        if apply:
            save(path, content, updated)
        return diff
