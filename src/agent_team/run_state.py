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
from agent_team.recovery import (
    classify_evidence,
    classify_review_binding,
    discover_runs,
    fingerprint_workspace,
    select_run,
)
from agent_team.runs import utc_now, validate_run
from agent_team.templates import asset_text
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
        review_table = data.get("review", {})
        has_override_reason = (
            isinstance(review_table, dict)
            and isinstance(review_table.get("limit_override_reason"), str)
            and bool(review_table["limit_override_reason"].strip())
        )
        changes: dict[tuple[str, ...], Any] = {
            ("max_workers",): tier.max_workers,
            ("write_isolation",): tier.write_isolation,
            ("reports_required",): data["tier"] == "team" or (
                data["tier"] == "assisted" and config.workflow.persist_agent_reports
            ),
            ("review", "required"): tier.independent_review,
        }
        if not has_override_reason:
            changes[("review", "limit")] = config.workflow.review_cycle_limit
        if isinstance(review_table, dict):
            for key, expected in (
                ("re_review_mode", config.review.re_review_mode),
                ("nit_cap", config.review.nit_cap),
                ("policy_file", config.review.policy_file.as_posix()),
            ):
                if key in review_table:
                    changes[("review", key)] = expected
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


def _git_text(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        return result.stdout if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _extract_section(content: str, heading: str) -> str:
    match = re.search(rf"(?ms)^{re.escape(heading)}[ \t]*\n(.*?)(?=^## |\Z)", content)
    return match.group(1).strip() if match else ""


def prepare_review(
    root: Path,
    config: TeamConfig,
    slug: str,
    *,
    cycle: int | None = None,
    base_revision: str | None = None,
    output_format: str = "markdown",
    output_path: Path | None = None,
) -> str:
    candidate, _ = select_run(discover_runs(root, config), root, slug=slug)
    if candidate is None or candidate.errors:
        fail("prepare-review requires a readable run")
    manifest = candidate.manifest
    review_table = manifest.get("review", {}) if isinstance(manifest.get("review"), dict) else {}
    used = review_table.get("used", 0) if isinstance(review_table.get("used"), int) else 0
    limit = (
        review_table.get("limit", config.workflow.review_cycle_limit)
        if isinstance(review_table.get("limit"), int)
        else config.workflow.review_cycle_limit
    )
    verdict = str(review_table.get("verdict", "unknown"))
    if cycle is None:
        target_cycle = max(1, used + 1)
    else:
        if cycle < 1:
            fail("cycle must be >= 1")
        target_cycle = cycle
    review_mode = "full-scope" if target_cycle == 1 else config.review.re_review_mode

    run_dir = candidate.path.parent
    artifacts = manifest.get("artifacts", {}) if isinstance(manifest.get("artifacts"), dict) else {}
    review_rel = artifacts.get("review", "review.md")
    review_file = (run_dir / review_rel).resolve() if isinstance(review_rel, str) and review_rel else None
    prior_review_text = ""
    if (
        review_file is not None
        and review_file.is_relative_to(run_dir.resolve())
        and review_file.is_file()
    ):
        try:
            prior_review_text = review_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            prior_review_text = ""

    prior_revision_match = re.findall(r"(?m)^- Revision: (.+?)[ \t]*$", prior_review_text)
    prior_review_revision = (
        prior_revision_match[0].strip().strip("`") if len(prior_revision_match) == 1 else None
    )
    if prior_review_revision in {"pending", "unknown", ""}:
        prior_review_revision = None

    baseline_revision = str(manifest.get("git", {}).get("baseline_revision", "unknown"))
    last_reviewed = review_table.get("last_reviewed_revision")
    if not isinstance(last_reviewed, str) or not last_reviewed.strip():
        last_reviewed = prior_review_revision

    if base_revision and base_revision.strip():
        effective_base = base_revision.strip()
    elif target_cycle >= 2 and review_mode == "diff-only" and last_reviewed:
        effective_base = last_reviewed
    else:
        effective_base = baseline_revision

    workspace = asdict(fingerprint_workspace(root))
    evidence = classify_evidence(manifest, workspace)
    binding = classify_review_binding(candidate, workspace)

    excluded = (
        ".agent-team",
        ".claude/settings.local.json",
        ".codex/hooks.json",
        ".agents/hooks.json",
    )
    pathspec = ["--", ".", *(f":(exclude){path}" for path in excluded)]
    diff_target = effective_base if effective_base not in {"unknown", "pending", ""} else "HEAD"
    name_status_out = _git_text(root, "diff", "--name-status", diff_target, *pathspec)
    if name_status_out is None and diff_target != "HEAD":
        diff_target = "HEAD"
        name_status_out = _git_text(root, "diff", "--name-status", "HEAD", *pathspec)
    stat_out = _git_text(root, "diff", "--stat", diff_target, *pathspec) or ""
    changed_files = [
        line.strip() for line in (name_status_out or "").splitlines() if line.strip()
    ]

    prior_findings = _extract_section(prior_review_text, "## Findings") if prior_review_text else ""
    prior_risks = (
        _extract_section(prior_review_text, "## Residual risks and gaps")
        if prior_review_text
        else ""
    )

    policy_rel = config.review.policy_file
    policy_path = (root / policy_rel).resolve()
    policy_exists = policy_path.is_relative_to(root.resolve()) and policy_path.is_file()
    policy_excerpt = ""
    if policy_exists:
        try:
            policy_excerpt = policy_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            policy_excerpt = ""
    if not policy_excerpt:
        try:
            policy_excerpt = asset_text("templates", "workflow", "REVIEW.md.tpl").strip()
        except Exception:
            policy_excerpt = ""

    tracked_digest = workspace["tracked_diff_sha256"] or "clean"
    untracked_digest = workspace["untracked_sha256"] or "clean"

    payload: dict[str, Any] = {
        "slug": slug,
        "cycle": target_cycle,
        "limit": limit,
        "used": used,
        "current_verdict": verdict,
        "review_mode": review_mode,
        "bug_class_sweep": config.review.bug_class_sweep if target_cycle == 1 else False,
        "nit_cap": config.review.nit_cap,
        "treat_preexisting_as_nonblocking": config.review.treat_preexisting_as_nonblocking,
        "re_review_on_advisory_fix": config.review.re_review_on_advisory_fix,
        "policy_file": policy_rel.as_posix(),
        "policy_exists": policy_exists,
        "base_revision": effective_base,
        "baseline_revision": baseline_revision,
        "workspace": {
            "revision": workspace["revision"],
            "tracked_diff_sha256": tracked_digest,
            "untracked_sha256": untracked_digest,
        },
        "review_binding": binding,
        "changed_files": changed_files,
        "diff_stat": stat_out.strip(),
        "evidence": evidence,
        "prior_findings": prior_findings,
        "prior_residual_risks": prior_risks,
    }

    if output_format == "json":
        rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    else:
        changed_lines = (
            "\n".join(f"- `{entry}`" for entry in changed_files)
            if changed_files
            else "- (no tracked changes relative to base revision)"
        )
        evidence_lines = (
            "\n".join(
                f"- `{item['state']}`: `{item['command']}` (at `{item['at']}`)"
                for item in evidence
            )
            if evidence
            else "- `unbound`: no verification checks recorded yet"
        )
        lines = [
            f"# Review Packet: `{slug}` (Cycle {target_cycle} / {limit})",
            "",
            "## Recommended `review.md` Header Block",
            "",
            "```markdown",
            f"- Run: `{slug}`",
            f"- Cycle: {target_cycle}",
            f"- Review-Mode: {review_mode}",
            f"- Base-Revision: {effective_base}",
            f"- Revision: {workspace['revision']}",
            f"- Tracked-Diff-SHA256: {tracked_digest}",
            f"- Untracked-SHA256: {untracked_digest}",
            f"- Updated: {utc_now()}",
            "- Verdict: pending",
            "```",
            "",
            "## Effective Convergence Policy",
            "",
            f"- Review mode: `{review_mode}`",
            f"- Cycle 1 Bug-Class Sweep required: `{'true' if payload['bug_class_sweep'] else 'false'}`",
            f"- Non-blocking `Nit` cap: `{config.review.nit_cap}`",
            f"- Pre-existing issues non-blocking: `{'true' if config.review.treat_preexisting_as_nonblocking else 'false'}`",
            f"- Re-review on optional `Nit` advisory fixes: `{'true' if config.review.re_review_on_advisory_fix else 'false'}`",
            f"- Policy file: `{policy_rel.as_posix()}` ({'present' if policy_exists else 'absent'})",
            f"- Previous review binding state: `{binding['state']}` (used={used}, verdict={verdict})",
            "",
            "## Scope & Diff Summary",
            "",
            f"- Baseline revision: `{baseline_revision}`",
            f"- Base revision for this cycle: `{effective_base}`",
            f"- Current revision: `{workspace['revision']}`",
            "",
            "### Changed Files",
            "",
            changed_lines,
        ]
        if stat_out.strip():
            lines.extend(["", "### Diff Stat", "", "```text", stat_out.strip(), "```"])
        lines.extend(["", "## Verification Evidence", "", evidence_lines])
        if target_cycle >= 2 and prior_findings:
            lines.extend([
                "",
                "## Prior Cycle Findings (Verify Dispositions Only in `diff-only` Mode)",
                "",
                prior_findings,
            ])
        if target_cycle >= 2 and prior_risks:
            lines.extend(["", "## Prior Residual Risks and Gaps", "", prior_risks])
        if policy_excerpt:
            lines.extend(["", f"## Repository Review Policy (`{policy_rel.as_posix()}`)", "", policy_excerpt])
        rendered = "\n".join(lines) + "\n"

    if output_path is not None:
        resolved_out = (root / output_path).resolve() if not output_path.is_absolute() else output_path.resolve()
        if not resolved_out.is_relative_to(root.resolve()):
            fail("prepare-review output path must remain inside the project")
        atomic_write(resolved_out, rendered)
    return rendered
