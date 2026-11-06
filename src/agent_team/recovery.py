from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_team.diagnostics import Diagnostic, ValidationFailure
from agent_team.models import TeamConfig

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TERMINAL = {"complete", "cancelled"}


@dataclass
class RunCandidate:
    slug: str
    path: Path
    manifest: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return bool(self.errors) or self.manifest.get("status") not in _TERMINAL

    def to_dict(self) -> dict[str, Any]:
        return {"slug": self.slug, "path": str(self.path),
                "status": self.manifest.get("status", "unknown"),
                "tier": self.manifest.get("tier", "unknown"), "errors": self.errors}


@dataclass
class WorkspaceIdentity:
    revision: str = "unknown"
    tracked_diff_sha256: str = "unknown"
    untracked_sha256: str = "unknown"


def _failure(message: str) -> ValidationFailure:
    return ValidationFailure([Diagnostic("resume", message, code="recovery")])


def _inside(path: Path, parent: Path) -> bool:
    return path != parent and parent in path.parents


def discover_runs(root: Path, config: TeamConfig) -> list[RunCandidate]:
    root = root.resolve()
    run_root = (root / config.workflow.run_root).resolve()
    if not _inside(run_root, root):
        raise _failure("configured run root escapes the project")
    candidates: list[RunCandidate] = []
    try:
        directories = sorted(run_root.iterdir()) if run_root.exists() else []
        for directory in directories:
            if not directory.is_dir() or not _SLUG.fullmatch(directory.name):
                continue
            candidate = RunCandidate(directory.name, directory / "run.toml")
            if not _inside(directory.resolve(), run_root):
                candidate.errors.append("run directory escapes configured run root")
            elif not _inside(candidate.path.resolve(), directory.resolve()):
                candidate.errors.append("manifest escapes run directory")
            else:
                try:
                    candidate.manifest = tomllib.loads(candidate.path.read_text(encoding="utf-8"))
                    if candidate.manifest.get("slug") != directory.name:
                        candidate.errors.append("manifest slug does not match directory")
                    status = candidate.manifest.get("status")
                    if not isinstance(status, str) or status not in {
                        "discovery", "planned", "implementing", "reviewing",
                        "complete", "blocked", "cancelled",
                    }:
                        candidate.errors.append("invalid or missing run status")
                    if candidate.manifest.get("schema_version") != 1:
                        candidate.errors.append("unsupported manifest schema version")
                    for key in ("git", "gates", "artifacts", "review"):
                        if not isinstance(candidate.manifest.get(key, {}), dict):
                            candidate.errors.append(f"{key} must be a table")
                    tasks = candidate.manifest.get("tasks", [])
                    if not isinstance(tasks, list) or any(not isinstance(t, dict) for t in tasks):
                        candidate.errors.append("tasks must be an array of tables")
                except (OSError, ValueError) as exc:
                    candidate.errors.append(f"cannot read manifest: {exc}")
            candidates.append(candidate)
    except OSError as exc:
        raise _failure(f"cannot discover runs: {exc}") from exc
    return candidates


def select_run(
    candidates: list[RunCandidate], root: Path, *, slug: str | None = None,
    session_id: str | None = None, session_only: bool = False,
) -> tuple[RunCandidate | None, list[str]]:
    if slug is not None:
        if not _SLUG.fullmatch(slug):
            raise _failure("invalid run slug")
        selected = next((item for item in candidates if item.slug == slug), None)
        if selected is None:
            raise _failure(f"run not found: {slug}")
        return selected, []
    root = root.resolve()
    active = [item for item in candidates if item.active]
    notices: list[str] = []
    session_id = session_id or os.environ.get("AGENT_TEAM_SESSION_ID")
    names = ([hashlib.sha256(session_id.encode()).hexdigest()[:16] + ".json"]
             if session_id else []) + ([] if session_only else ["current.json"])
    for name in names:
        pointer = root / ".agent-team" / "sessions" / name
        if not _inside(pointer.resolve(), root):
            notices.append(f"ignored pointer outside project: {name}")
            continue
        if not pointer.exists():
            continue
        try:
            data = json.loads(pointer.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("project_root") != str(root):
                raise ValueError("project identity mismatch")
            if name != "current.json" and data.get("session_id_hash") != name[:-5]:
                raise ValueError("session identity mismatch")
            selected = next((item for item in active if item.slug == data.get("run_slug")), None)
            if selected is None or selected.errors:
                raise ValueError("run is missing, terminal or unreadable")
            expected = selected.path.parent.relative_to(root).as_posix()
            if data.get("run_path") != expected:
                raise ValueError("run path mismatch")
            return selected, notices
        except (OSError, ValueError, TypeError) as exc:
            notices.append(f"ignored invalid pointer {name}: {exc}")
    if session_only:
        # Hooks must not adopt a session through the project fallback. A missing
        # per-session pointer is a normal "not managed by agent-team" state.
        return None, notices
    return (active[0] if len(active) == 1 else None), notices


def fingerprint_workspace(root: Path) -> WorkspaceIdentity:
    def git(*args: str) -> bytes | None:
        try:
            result = subprocess.run(
                ["git", *args], cwd=root, capture_output=True, check=False, timeout=10,
            )
            return result.stdout if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    # agent-team's own state must not invalidate evidence: recording a check
    # rewrites run.toml, and pointer/backup files appear during recovery.
    excluded = (".agent-team", ".claude/settings.local.json", ".codex/hooks.json",
                ".agents/hooks.json")
    pathspec = ["--", ".", *(f":(exclude){path}" for path in excluded)]
    identity = WorkspaceIdentity()
    revision = git("rev-parse", "HEAD")
    if revision is not None:
        identity.revision = revision.decode("ascii", errors="replace").strip()
    diff = git("diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD", *pathspec)
    if diff is not None:
        identity.tracked_diff_sha256 = hashlib.sha256(diff).hexdigest() if diff else ""
    untracked = git("ls-files", "--others", "--exclude-standard", "-z", *pathspec)
    if untracked is None:
        return identity
    paths = sorted(path for path in untracked.split(b"\0") if path)
    if len(paths) > 1000:
        identity.untracked_sha256 = "dirty-unbounded"
        return identity
    digest = hashlib.sha256()
    total = 0
    try:
        for raw in paths:
            path = root / os.fsdecode(raw)
            if path.is_symlink() or not path.is_file() or not _inside(path.resolve(), root.resolve()):
                identity.untracked_sha256 = "dirty-unbounded"
                return identity
            size = path.stat().st_size
            total += size
            if total > 16 * 1024 * 1024:
                identity.untracked_sha256 = "dirty-unbounded"
                return identity
            with path.open("rb") as stream:
                content = stream.read(16 * 1024 * 1024 + 1)
            if len(content) > 16 * 1024 * 1024 or len(content) != size:
                identity.untracked_sha256 = "dirty-unbounded"
                return identity
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
            digest.update(hashlib.sha256(content).digest())
        identity.untracked_sha256 = digest.hexdigest() if paths else ""
    except OSError:
        identity.untracked_sha256 = "unknown"
    return identity


def classify_workers(
    manifest: dict[str, Any], now: datetime | None = None, ttl: int = 1800,
) -> list[dict[str, Any]]:
    now = now or datetime.now(UTC)
    workers = []
    for task in manifest.get("tasks", []):
        status = task.get("status")
        status = status if isinstance(status, str) else "unknown"
        lease = task.get("lease")
        state = "unknown"
        paths: list[str] = []
        if isinstance(lease, dict):
            owned = lease.get("owned_paths")
            if isinstance(owned, list) and owned and all(isinstance(p, str) and p for p in owned):
                paths = owned
        if status in _TERMINAL and not lease:
            state = "released"
        elif status in {"pending", "ready", "blocked"}:
            state = "stale-lease" if lease else "not-running"
        elif status == "running" and isinstance(lease, dict) and paths:
            try:
                observed = datetime.fromisoformat(lease["last_observed_at"])
                age = (now - observed).total_seconds()
                if (lease.get("host") == socket.gethostname() and 0 <= age <= ttl
                        and all(isinstance(lease.get(k), str) and lease[k]
                                for k in ("owner", "token", "claimed_at"))):
                    state = "live_unverified"
            except (KeyError, TypeError, ValueError, AttributeError):
                pass
        workers.append({"id": task.get("id", "unknown"), "role": task.get("role", "unknown"),
                        "instance": task.get("instance", "unknown"), "state": state,
                        "owned_paths": paths})
    return workers


def config_drift(candidate: RunCandidate, config: TeamConfig) -> list[str]:
    manifest = candidate.manifest
    tier = config.tiers.get(manifest.get("tier")) if isinstance(manifest.get("tier"), str) else None
    if tier is None:
        return ["unknown tier; reconcile configuration before continuing"]
    drift = []
    expected_values = {
        "max_workers": tier.max_workers,
        "write_isolation": tier.write_isolation,
        "reports_required": manifest.get("tier") == "team" or (
            manifest.get("tier") == "assisted" and config.workflow.persist_agent_reports
        ),
    }
    for key, expected in expected_values.items():
        if manifest.get(key) != expected:
            drift.append(f"{key}: {manifest.get(key)} -> {expected}")
    review = manifest.get("review", {})
    if isinstance(review, dict):
        if review.get("required") != tier.independent_review:
            drift.append(f"review.required: {review.get('required')} -> {tier.independent_review}")
        has_override_reason = (
            isinstance(review.get("limit_override_reason"), str)
            and bool(review["limit_override_reason"].strip())
        )
        if not has_override_reason and review.get("limit") != config.workflow.review_cycle_limit:
            drift.append(f"review.limit: {review.get('limit')} -> {config.workflow.review_cycle_limit}")
        for key, expected in (
            ("re_review_mode", config.review.re_review_mode),
            ("nit_cap", config.review.nit_cap),
            ("policy_file", config.review.policy_file.as_posix()),
        ):
            if key in review and review.get(key) != expected:
                drift.append(f"review.{key}: {review.get(key)} -> {expected}")
    return drift


def classify_evidence(manifest: dict[str, Any], workspace: dict[str, str]) -> list[dict[str, Any]]:
    records = manifest.get("verification", [])
    if not isinstance(records, list):
        return [{"command": "unknown", "state": "unbound"}]
    classified = []
    keys = ("revision", "tracked_diff_sha256", "untracked_sha256")
    for record in records:
        if not isinstance(record, dict):
            classified.append({"command": "unknown", "state": "unbound"})
            continue
        identity = {key: record.get(key) for key in keys}
        if type(record.get("exit_status")) is not int:
            state = "unbound"
        elif record["exit_status"] != 0:
            state = "failed"
        elif (not isinstance(identity["revision"], str)
              or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", identity["revision"])
              or any(not isinstance(identity[key], str)
                     or not (identity[key] == "" or re.fullmatch(r"[0-9a-f]{64}", identity[key]))
                     for key in ("tracked_diff_sha256", "untracked_sha256"))
              or any(value in {"unknown", "dirty-unbounded"} for value in workspace.values())):
            state = "unbound"
        elif identity != workspace:
            state = "stale"
        else:
            state = "bound"
        classified.append({"command": record.get("command", "unknown"), "state": state,
                           "at": record.get("at", "unknown")})
    return classified


def recovery_status(
    candidate: RunCandidate, root: Path, config: TeamConfig,
) -> dict[str, Any]:
    if candidate.errors:
        raise _failure(f"unreadable run {candidate.slug}: {'; '.join(candidate.errors)}")
    manifest = candidate.manifest
    workers = classify_workers(manifest)
    gates = [str(key) for key, value in manifest.get("gates", {}).items() if value is not True]
    drift = config_drift(candidate, config)
    workspace = asdict(fingerprint_workspace(root))
    evidence = classify_evidence(manifest, workspace)
    unresolved = any(w["state"] in {"unknown", "live_unverified", "stale-lease"} for w in workers)
    if unresolved:
        next_step = "核实未闭合 worker 的所有权和执行状态，再恢复写操作。"
    elif drift:
        next_step = "核对配置漂移；按计划确认策略后再继续，禁止自动改写 manifest。"
    elif any(record["state"] != "bound" for record in evidence):
        next_step = "重跑 failed、stale 或 unbound 的检查，重新绑定当前工作区证据。"
    elif gates:
        next_step = f"读取 run 工件并完成首个未满足 gate：{gates[0]}。"
    elif manifest.get("status") in _TERMINAL:
        next_step = "该 run 已结束；只读检查报告，不重放已完成操作。"
    else:
        next_step = "读取 plan、decisions 和已完成报告，核对任务依赖后继续。"
    return {**candidate.to_dict(), "baseline_revision": manifest.get("git", {}).get("baseline_revision", "unknown"),
            "workspace": workspace, "workers": workers,
            "open_gates": gates, "config_drift": drift, "evidence": evidence, "next": next_step}


def render_context(status: dict[str, Any], limit: int = 9000) -> str:
    if not 512 <= limit <= 9000:
        raise ValueError("context limit must be between 512 and 9000")
    workspace = status["workspace"]
    lines = [f"Run: {status['slug']} | {status['path']} | status={status['status']} | tier={status['tier']}",
             f"Revision: baseline={status['baseline_revision']} current={workspace['revision']}",
             f"Workspace: tracked_diff={workspace['tracked_diff_sha256']} untracked={workspace['untracked_sha256']}",
             "Evidence: " + (", ".join(
                 f"{sum(r['state'] == state for r in status['evidence'])} {state}"
                 for state in ("bound", "stale", "unbound", "failed"))
                 if status["evidence"] else "unbound（无记录；恢复前重跑适用检查）"),
             f"Gates: {', '.join(status['open_gates']) or 'none'}",
             f"Next: {status['next']}",
             "Recovery rules: 先读 run.toml、requirements、plan、decisions 和报告；不重放未确认副作用；部分输出不是完成。"]
    workers = status["workers"]
    if any(w["state"] in {"unknown", "live_unverified", "stale-lease"} for w in workers):
        lines.insert(1, "WARNING: worker 未核实，暂停所有写操作；对账全部所有权后才可恢复，lease 不证明存活。")
    mandatory = "\n".join(lines)
    if len(mandatory) > limit:
        # 极端身份长度时，整体停止比丢失告警后继续更安全。
        return "WARNING: 恢复摘要必要字段超出预算，暂停所有写操作。请使用 resume status --json 检查完整身份、worker、gates 与下一步。"
    details = ["Config drift: " + ("; ".join(status["config_drift"]) or "none")]
    details.extend(f"Worker: {w['id']} {w['role']} {w['instance']} {w['state']} owned_paths={w['owned_paths']}"
                   for w in workers)
    details.extend(f"Check: {record['state']} {record['command']}" for record in status["evidence"])
    text = mandatory
    suffix = "\n[详细信息超限；使用 resume status --json 查看全部 worker 与配置差异]"
    for detail in details:
        if len(text) + len(detail) + 1 + len(suffix) > limit:
            return text + suffix if len(text) + len(suffix) <= limit else text
        text += "\n" + detail
    return text
