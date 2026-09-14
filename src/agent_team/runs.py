from __future__ import annotations

import json
import re
import socket
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_team.diagnostics import Diagnostic, ValidationFailure
from agent_team.fs import atomic_write, non_directory_parent
from agent_team.models import ROLE_IDS, TIERS, TeamConfig
from agent_team.templates import asset_text, render_template, required_markers

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TASK_ID = re.compile(r"^T-[0-9]{3}$")
_STATUSES = {"discovery", "planned", "implementing", "reviewing", "complete", "blocked", "cancelled"}
_TASK_STATUSES = {"pending", "ready", "running", "complete", "blocked", "cancelled"}
_VERDICTS = {"pending", "approved", "changes-requested", "blocked", "not-required"}
_REPORT_SECTIONS = (
    "## Scope and acceptance evidence",
    "## Changed files",
    "## Verification",
    "## Documentation",
    "## Blockers and residual risks",
)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_value(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments], cwd=root, text=True, capture_output=True, check=False
        )
    except OSError:
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _run_manifest(
    *, slug: str, title: str, created_at: str, tier: str, model_preset: str,
    host: str, repository: str, baseline: str, branch: str,
    worktree_decision: str, review_required: bool, review_limit: int,
    max_workers: int, write_isolation: str, reports_required: bool,
    artifacts: dict[str, str],
    worktree_gate: bool, worker_gate: bool,
) -> str:
    lines = [
        "schema_version = 1",
        f"slug = {_toml_string(slug)}",
        f"title = {_toml_string(title)}",
        f"created_at = {_toml_string(created_at)}",
        f"updated_at = {_toml_string(created_at)}",
        'status = "discovery"',
        f"tier = {_toml_string(tier)}",
        f"max_workers = {max_workers}",
        f"write_isolation = {_toml_string(write_isolation)}",
        f"reports_required = {'true' if reports_required else 'false'}",
        f"model_preset = {_toml_string(model_preset)}",
        f"host = {_toml_string(host)}",
        "",
        "[git]",
        f"repository = {_toml_string(repository)}",
        f"baseline_revision = {_toml_string(baseline)}",
        f"branch = {_toml_string(branch)}",
        f"worktree_decision = {_toml_string(worktree_decision)}",
        "",
        "[review]",
        f"required = {'true' if review_required else 'false'}",
        f"limit = {review_limit}",
        "used = 0",
        f"verdict = {_toml_string('pending' if review_required else 'not-required')}",
        "",
        "[gates]",
        "requirements = false",
        "design = true",
        "plan = false",
        f"worktree = {'true' if worktree_gate else 'false'}",
        "live_validation = false",
        f"worker_closure = {'true' if worker_gate else 'false'}",
        "",
        "[artifacts]",
    ]
    lines.extend(f"{key} = {_toml_string(value)}" for key, value in artifacts.items())
    return "\n".join(lines) + "\n"


def init_run(
    root: Path,
    config: TeamConfig,
    slug: str,
    title: str | None,
    tier: str,
    model_preset: str,
) -> Path:
    if not _SLUG.fullmatch(slug):
        raise ValidationFailure([
            Diagnostic("slug", "must contain lowercase letters, digits, and single hyphens", code="format")
        ])
    if tier not in TIERS:
        raise ValidationFailure([Diagnostic("tier", "must be solo, assisted, or team", code="enum")])
    project_root = root.resolve()
    run_root = (project_root / config.workflow.run_root).resolve()
    if run_root != project_root and project_root not in run_root.parents:
        raise ValidationFailure([
            Diagnostic("workflow.run_root", "run root escapes the project", code="path")
        ])
    destination = (run_root / slug).resolve()
    if destination == run_root or run_root not in destination.parents:
        raise ValidationFailure([Diagnostic("slug", "run path escapes configured run root", code="path")])
    if destination.exists():
        raise ValidationFailure([Diagnostic(str(destination), "run already exists", code="exists")])
    blocker = non_directory_parent(project_root, destination)
    if blocker is not None:
        raise ValidationFailure([
            Diagnostic(str(destination), f"parent path is not a directory: {blocker}", code="parent")
        ])

    display_title = title or slug.replace("-", " ").title()
    timestamp = utc_now()
    durable = config.tiers[tier].durable_artifacts
    review_required = config.tiers[tier].independent_review
    reports_required = tier == "team" or (
        tier == "assisted" and config.workflow.persist_agent_reports
    )
    artifacts: dict[str, str] = {}
    if durable or tier == "solo":
        artifacts.update({"requirements": "requirements.md", "plan": "plan.md"})
    if config.workflow.deep_discovery_default:
        artifacts.update({"design": "design.md", "decisions": "decisions.md"})
    if tier == "team":
        artifacts["tasks"] = "tasks.md"
    if review_required:
        artifacts["review"] = "review.md"
    if durable:
        artifacts["final_report"] = "final-report.md"

    destination.mkdir(parents=True)
    variables = {
        "slug": slug,
        "title": display_title,
        "created_at": timestamp,
        "updated_at": timestamp,
        "tier": tier,
        "model_preset": model_preset,
        "host": socket.gethostname(),
        "task_id": "T-001",
        "role": "implementer",
        "cycle": "1",
    }
    template_for = {
        "requirements": "requirements.md.tpl",
        "design": "design.md.tpl",
        "decisions": "decisions.md.tpl",
        "plan": "plan.md.tpl",
        "tasks": "tasks.md.tpl",
        "review": "review.md.tpl",
        "final_report": "final-report.md.tpl",
    }
    for key, relative in artifacts.items():
        template = asset_text("templates", "workflow", template_for[key])
        atomic_write(destination / relative, render_template(template, variables))
    if reports_required:
        (destination / "reports").mkdir()
        template = asset_text("templates", "workflow", "agent-report.md.tpl")
        template_variables = {
            **variables,
            "task_id": "<task-id>",
            "role": "<role>",
        }
        atomic_write(
            destination / "reports" / "agent-report-template.md",
            render_template(template, template_variables),
        )

    git_file = root / ".git"
    worktree_decision = "created" if git_file.is_file() else "pending"
    worktree_gate = worktree_decision == "created" or not config.workflow.require_worktree_decision
    manifest = _run_manifest(
        slug=slug,
        title=display_title,
        created_at=timestamp,
        tier=tier,
        model_preset=model_preset,
        host=variables["host"],
        repository=str(root.resolve()),
        baseline=_git_value(root, "rev-parse", "HEAD"),
        branch=_git_value(root, "branch", "--show-current"),
        worktree_decision=worktree_decision,
        review_required=review_required,
        review_limit=config.workflow.review_cycle_limit,
        max_workers=config.tiers[tier].max_workers,
        write_isolation=config.tiers[tier].write_isolation,
        reports_required=reports_required,
        artifacts=artifacts,
        worktree_gate=worktree_gate,
        worker_gate=tier == "solo",
    )
    if config.workflow.deep_discovery_default:
        manifest = manifest.replace("design = true", "design = false", 1)
    atomic_write(destination / "run.toml", manifest)
    return destination


def _unknown(data: dict[str, Any], allowed: set[str], prefix: str, diagnostics: list[Diagnostic]) -> None:
    for key in sorted(set(data) - allowed):
        diagnostics.append(Diagnostic(f"{prefix}.{key}".strip("."), "unknown key", code="unknown-key"))


def _table(data: dict[str, Any], key: str, prefix: str, diagnostics: list[Diagnostic]) -> dict[str, Any]:
    value = data.get(key)
    if isinstance(value, dict):
        return value
    diagnostics.append(Diagnostic(f"{prefix}.{key}".strip("."), "required table is missing", code="required"))
    return {}


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return value.endswith("Z")


def _report_contract_issues(
    content: str,
    *,
    slug: str,
    task_id: str,
    role: str,
    template: bool = False,
) -> tuple[str, ...]:
    issues: list[str] = []
    expected_header = f"# Agent Report: {task_id} / {role}"
    if not content.startswith(expected_header + "\n"):
        issues.append(f"header must be {expected_header}")
    expected_run = f"- Run: `{slug}`"
    if not re.search(rf"(?m)^{re.escape(expected_run)}[ \t]*$", content):
        issues.append(f"missing {expected_run}")
    for heading in _REPORT_SECTIONS:
        match = re.search(
            rf"(?ms)^{re.escape(heading)}[ \t]*\n(.*?)(?=^## |\Z)",
            content,
        )
        if match is None:
            issues.append(f"missing {heading}")
        elif not match.group(1).strip():
            issues.append(f"empty {heading}")
        elif template and not required_markers(match.group(1)):
            issues.append(f"missing REQUIRED marker in {heading}")
    return tuple(issues)


def validate_run(
    path: Path,
    config: TeamConfig,
    allowed_roles: set[str] | None = None,
    writable_roles: set[str] | None = None,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    label = str(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [Diagnostic(label, str(exc), code="toml")]
    _unknown(
        data,
        {"schema_version", "slug", "title", "created_at", "updated_at", "status", "tier", "max_workers", "write_isolation", "reports_required", "model_preset", "host", "git", "review", "gates", "artifacts", "tasks"},
        label, diagnostics,
    )
    if data.get("schema_version") != 1:
        diagnostics.append(Diagnostic(f"{label}.schema_version", "only schema version 1 is supported", code="enum"))
    for key in ("title", "host"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            diagnostics.append(Diagnostic(f"{label}.{key}", "must be a non-empty string", code="required"))
    slug = data.get("slug")
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug) or path.parent.name != slug:
        diagnostics.append(Diagnostic(f"{label}.slug", "must match the containing run directory", code="invariant"))
    status = data.get("status")
    if status not in _STATUSES:
        diagnostics.append(Diagnostic(f"{label}.status", "unsupported lifecycle status", code="enum"))
    tier = data.get("tier")
    if tier not in TIERS:
        diagnostics.append(Diagnostic(f"{label}.tier", "unsupported workflow tier", code="enum"))
    max_workers = data.get("max_workers")
    if not isinstance(max_workers, int) or isinstance(max_workers, bool) or max_workers < 0:
        diagnostics.append(Diagnostic(f"{label}.max_workers", "must be a non-negative integer", code="range"))
    elif tier in TIERS and max_workers != config.tiers[tier].max_workers:
        diagnostics.append(Diagnostic(
            f"{label}.max_workers", "must match the selected tier's configured limit", code="invariant"
        ))
    write_isolation = data.get("write_isolation")
    if not isinstance(write_isolation, str) or not write_isolation:
        diagnostics.append(Diagnostic(
            f"{label}.write_isolation", "must be a non-empty string", code="type"
        ))
    elif tier in TIERS and write_isolation != config.tiers[tier].write_isolation:
        diagnostics.append(Diagnostic(
            f"{label}.write_isolation",
            "must match the selected tier's write-isolation policy",
            code="invariant",
        ))
    reports_required = data.get("reports_required")
    if not isinstance(reports_required, bool):
        diagnostics.append(Diagnostic(f"{label}.reports_required", "must be a boolean", code="type"))
    elif tier in TIERS:
        expected_reports = tier == "team" or (
            tier == "assisted" and config.workflow.persist_agent_reports
        )
        if reports_required != expected_reports:
            diagnostics.append(Diagnostic(
                f"{label}.reports_required", "must match the effective project reporting policy", code="invariant"
            ))
    if data.get("model_preset") not in {"economy", "balanced", "quality"}:
        diagnostics.append(Diagnostic(f"{label}.model_preset", "unsupported model preset", code="enum"))
    for key in ("created_at", "updated_at"):
        if not _valid_timestamp(data.get(key)):
            diagnostics.append(Diagnostic(f"{label}.{key}", "must be RFC3339 UTC", code="format"))
    if _valid_timestamp(data.get("created_at")) and _valid_timestamp(data.get("updated_at")):
        created = datetime.fromisoformat(data["created_at"])
        updated = datetime.fromisoformat(data["updated_at"])
        if updated < created:
            diagnostics.append(Diagnostic(f"{label}.updated_at", "cannot precede created_at", code="invariant"))

    git = _table(data, "git", label, diagnostics)
    _unknown(git, {"repository", "baseline_revision", "branch", "worktree_decision"}, f"{label}.git", diagnostics)
    for key in ("repository", "baseline_revision", "branch", "worktree_decision"):
        if not isinstance(git.get(key), str) or not git.get(key):
            diagnostics.append(Diagnostic(f"{label}.git.{key}", "must be a non-empty string", code="required"))
    worktree_decision = git.get("worktree_decision")
    if worktree_decision not in {"pending", "current-checkout", "created", "declined"}:
        diagnostics.append(Diagnostic(f"{label}.git.worktree_decision", "unsupported decision", code="enum"))

    review = _table(data, "review", label, diagnostics)
    _unknown(review, {"required", "limit", "used", "verdict"}, f"{label}.review", diagnostics)
    required = review.get("required")
    limit = review.get("limit")
    used = review.get("used")
    verdict = review.get("verdict")
    if not isinstance(required, bool):
        diagnostics.append(Diagnostic(f"{label}.review.required", "must be a boolean", code="type"))
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 3:
        diagnostics.append(Diagnostic(f"{label}.review.limit", "must be between 1 and 3", code="range"))
    if not isinstance(used, int) or isinstance(used, bool) or used < 0 or isinstance(limit, int) and used > limit:
        diagnostics.append(Diagnostic(f"{label}.review.used", "must be non-negative and no greater than limit", code="range"))
    if verdict not in _VERDICTS:
        diagnostics.append(Diagnostic(f"{label}.review.verdict", "unsupported verdict", code="enum"))
    if tier == "team" and required is not True:
        diagnostics.append(Diagnostic(f"{label}.review.required", "team tier requires independent review", code="invariant"))
    if isinstance(required, bool) and tier in TIERS and required != config.tiers[tier].independent_review:
        diagnostics.append(Diagnostic(
            f"{label}.review.required", "must match the selected tier's review policy", code="invariant"
        ))
    if isinstance(limit, int) and not isinstance(limit, bool) and limit != config.workflow.review_cycle_limit:
        diagnostics.append(Diagnostic(f"{label}.review.limit", "must match project workflow.review_cycle_limit", code="invariant"))
    if required is False and verdict != "not-required":
        diagnostics.append(Diagnostic(f"{label}.review.verdict", "must be not-required when review is disabled", code="invariant"))
    if required is True and verdict == "not-required":
        diagnostics.append(Diagnostic(f"{label}.review.verdict", "cannot be not-required when review is required", code="invariant"))
    if (
        required is True
        and verdict in {"approved", "changes-requested", "blocked"}
        and isinstance(used, int)
        and not isinstance(used, bool)
        and used == 0
    ):
        diagnostics.append(Diagnostic(
            f"{label}.review.used", "must record at least one cycle for this verdict", code="invariant"
        ))

    gates = _table(data, "gates", label, diagnostics)
    gate_names = {"requirements", "design", "plan", "worktree", "live_validation", "worker_closure"}
    _unknown(gates, gate_names, f"{label}.gates", diagnostics)
    for gate in gate_names:
        if not isinstance(gates.get(gate), bool):
            diagnostics.append(Diagnostic(f"{label}.gates.{gate}", "must be a boolean", code="type"))
    if config.workflow.require_worktree_decision:
        expected_worktree_gate = worktree_decision != "pending"
        if isinstance(gates.get("worktree"), bool) and gates["worktree"] != expected_worktree_gate:
            diagnostics.append(Diagnostic(f"{label}.gates.worktree", "must reflect git.worktree_decision", code="invariant"))

    artifacts = _table(data, "artifacts", label, diagnostics)
    _unknown(artifacts, {"requirements", "design", "plan", "tasks", "decisions", "review", "final_report"}, f"{label}.artifacts", diagnostics)
    run_dir = path.parent.resolve()
    report_template = run_dir / "reports" / "agent-report-template.md"
    if reports_required is True:
        if not report_template.is_file():
            diagnostics.append(Diagnostic(
                f"{label}.reports",
                "report persistence requires reports/agent-report-template.md",
                code="required",
            ))
        else:
            try:
                template_content = report_template.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                diagnostics.append(Diagnostic(f"{label}.reports", str(exc), code="read"))
            else:
                template_issues = _report_contract_issues(
                    template_content,
                    slug=slug if isinstance(slug, str) else "<run-slug>",
                    task_id="<task-id>",
                    role="<role>",
                    template=True,
                )
                if template_issues:
                    diagnostics.append(Diagnostic(
                        f"{label}.reports",
                        "; ".join(template_issues),
                        code="report-contract",
                    ))
    for name, relative in artifacts.items():
        if not isinstance(relative, str) or not relative:
            diagnostics.append(Diagnostic(f"{label}.artifacts.{name}", "must be a non-empty relative path", code="type"))
            continue
        candidate = (run_dir / relative).resolve()
        if candidate != run_dir and run_dir not in candidate.parents:
            diagnostics.append(Diagnostic(f"{label}.artifacts.{name}", "must remain inside the run directory", code="path"))
            continue
        if not candidate.is_file():
            diagnostics.append(Diagnostic(f"{label}.artifacts.{name}", "artifact file does not exist", code="missing"))
            continue
        try:
            content = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            diagnostics.append(Diagnostic(f"{label}.artifacts.{name}", str(exc), code="read"))
            continue
        markers = required_markers(content)
        if markers:
            diagnostics.append(Diagnostic(
                f"{label}.artifacts.{name}",
                f"contains {len(markers)} unresolved REQUIRED marker(s)",
                severity="error" if status == "complete" else "warning",
                code="required-marker",
            ))
    required_artifacts = {"requirements", "plan"}
    if config.workflow.deep_discovery_default:
        required_artifacts.update({"design", "decisions"})
    if "design" in artifacts:
        required_artifacts.add("decisions")
    if required is True:
        required_artifacts.add("review")
    if tier == "team":
        required_artifacts.update({"tasks", "final_report"})
    elif tier == "assisted":
        required_artifacts.add("final_report")
    for artifact in sorted(required_artifacts - set(artifacts)):
        diagnostics.append(Diagnostic(f"{label}.artifacts.{artifact}", "required for this tier", code="required"))

    tasks = data.get("tasks", [])
    if not isinstance(tasks, list) or not all(isinstance(task, dict) for task in tasks):
        diagnostics.append(Diagnostic(f"{label}.tasks", "must be an array of tables", code="type"))
        tasks = []
    if tier == "solo" and tasks:
        diagnostics.append(Diagnostic(
            f"{label}.tasks", "solo runs cannot contain worker tasks", code="tier"
        ))
    task_allowed = {"id", "group", "role", "instance", "status", "deps", "report"}
    task_ids: set[str] = set()
    instances: set[str] = set()
    dependency_map: dict[str, tuple[str, ...]] = {}
    task_statuses: dict[str, str] = {}
    known_roles = (allowed_roles or set(ROLE_IDS)) - {"coordinator"}
    known_writable_roles = (writable_roles or {"implementer", "ops"}) - {"coordinator"}
    for index, task in enumerate(tasks):
        prefix = f"{label}.tasks.{index}"
        _unknown(task, task_allowed, prefix, diagnostics)
        task_id = task.get("id")
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            diagnostics.append(Diagnostic(f"{prefix}.id", "must match T-NNN", code="format"))
            continue
        if task_id in task_ids:
            diagnostics.append(Diagnostic(f"{prefix}.id", "task ID must be unique", code="duplicate"))
        task_ids.add(task_id)
        group = task.get("group")
        if not isinstance(group, str) or not re.fullmatch(r"TG-[0-9]{2}", group):
            diagnostics.append(Diagnostic(f"{prefix}.group", "must match TG-NN", code="format"))
        instance = task.get("instance")
        if not isinstance(instance, str) or not instance.strip():
            diagnostics.append(Diagnostic(f"{prefix}.instance", "must be a non-empty string", code="required"))
        elif instance in instances:
            diagnostics.append(Diagnostic(f"{prefix}.instance", "worker instance must be unique", code="duplicate"))
        else:
            instances.add(instance)
        role = task.get("role")
        if role not in known_roles:
            diagnostics.append(Diagnostic(f"{prefix}.role", "unsupported role", code="enum"))
        task_status = task.get("status")
        if task_status not in _TASK_STATUSES:
            diagnostics.append(Diagnostic(f"{prefix}.status", "unsupported task status", code="enum"))
        else:
            task_statuses[task_id] = task_status
        deps = task.get("deps", [])
        if not isinstance(deps, list) or not all(isinstance(dep, str) for dep in deps):
            diagnostics.append(Diagnostic(f"{prefix}.deps", "must be an array of task IDs", code="type"))
            deps = []
        elif len(deps) != len(set(deps)):
            diagnostics.append(Diagnostic(f"{prefix}.deps", "dependency IDs must be unique", code="duplicate"))
        dependency_map[task_id] = tuple(deps)
        report = task.get("report")
        if report is None and reports_required is False:
            pass
        elif not isinstance(report, str) or not report.startswith("reports/") or ".." in Path(report).parts:
            diagnostics.append(Diagnostic(f"{prefix}.report", "must be a contained reports/ path", code="path"))
        elif isinstance(role, str) and report != f"reports/{task_id}-{role}.md":
            diagnostics.append(Diagnostic(f"{prefix}.report", "must match reports/<task-id>-<role>.md", code="invariant"))
        elif task.get("status") == "complete":
            report_path = (run_dir / report).resolve()
            if run_dir not in report_path.parents:
                diagnostics.append(Diagnostic(
                    f"{prefix}.report", "must remain inside the run directory", code="path"
                ))
            elif not report_path.is_file():
                diagnostics.append(Diagnostic(
                    f"{prefix}.report", "completed task report does not exist", code="missing"
                ))
            else:
                try:
                    report_content = report_path.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    diagnostics.append(Diagnostic(f"{prefix}.report", str(exc), code="read"))
                else:
                    contract_issues = _report_contract_issues(
                        report_content,
                        slug=slug if isinstance(slug, str) else "<run-slug>",
                        task_id=task_id,
                        role=role if isinstance(role, str) else "<role>",
                    )
                    if contract_issues:
                        diagnostics.append(Diagnostic(
                            f"{prefix}.report",
                            "; ".join(contract_issues),
                            code="report-contract",
                        ))
                    markers = required_markers(report_content)
                    if markers:
                        diagnostics.append(Diagnostic(
                            f"{prefix}.report",
                            f"contains {len(markers)} unresolved REQUIRED marker(s)",
                            severity="error" if status == "complete" else "warning",
                            code="required-marker",
                        ))
    for task_id, deps in dependency_map.items():
        for dep in deps:
            if dep not in task_ids:
                diagnostics.append(Diagnostic(f"{label}.tasks.{task_id}.deps", f"unknown dependency {dep}", code="reference"))
            elif (
                task_statuses.get(task_id) in {"ready", "running", "complete"}
                and task_statuses.get(dep) != "complete"
            ):
                diagnostics.append(Diagnostic(
                    f"{label}.tasks.{task_id}.deps",
                    f"dependency {dep} must be complete before task is {task_statuses[task_id]}",
                    code="dependency-state",
                ))
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            diagnostics.append(Diagnostic(f"{label}.tasks", f"dependency cycle includes {task_id}", code="cycle"))
            return
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in dependency_map.get(task_id, ()):
            if dependency in dependency_map:
                visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in dependency_map:
        visit(task_id)

    if isinstance(max_workers, int) and not isinstance(max_workers, bool):
        running_workers = sum(task.get("status") == "running" for task in tasks)
        if running_workers > max_workers:
            diagnostics.append(Diagnostic(
                f"{label}.tasks",
                f"{running_workers} running workers exceeds max_workers = {max_workers}",
                code="worker-limit",
            ))
    running_writers = sum(
        task.get("status") == "running" and task.get("role") in known_writable_roles
        for task in tasks
    )
    if tier == "assisted" and running_writers > 1:
        diagnostics.append(Diagnostic(
            f"{label}.tasks",
            f"{running_writers} running writers violates write_isolation = serialized",
            code="write-isolation",
        ))

    phase_gates = {
        "planned": ("requirements", "design", "plan"),
        "implementing": ("requirements", "design", "plan", "worktree"),
        "reviewing": ("requirements", "design", "plan", "worktree", "worker_closure"),
        "complete": ("requirements", "design", "plan", "worktree", "live_validation", "worker_closure"),
    }
    for gate in phase_gates.get(status, ()):
        if gates.get(gate) is not True:
            diagnostics.append(Diagnostic(f"{label}.gates.{gate}", f"must be true in {status} status", code="gate"))
    if status in {"reviewing", "complete"} and any(task.get("status") != "complete" for task in tasks):
        diagnostics.append(Diagnostic(f"{label}.tasks", f"all tasks must be complete in {status} status", code="gate"))
    if tier == "team" and status in {"reviewing", "complete"} and not tasks:
        diagnostics.append(Diagnostic(f"{label}.tasks", f"team runs require tasks in {status} status", code="gate"))
    if status == "complete" and required and verdict != "approved":
        diagnostics.append(Diagnostic(f"{label}.review.verdict", "must be approved before completion", code="gate"))
    return diagnostics


def validate_all_runs(root: Path, config: TeamConfig) -> list[Diagnostic]:
    run_root = root / config.workflow.run_root
    if not run_root.exists():
        return []
    from agent_team.config import load_roles

    diagnostics: list[Diagnostic] = []
    try:
        roles = load_roles(config, root)
        allowed_roles = {role.role_id for role in roles if role.role_id != "coordinator"}
        writable_roles = {
            role.role_id for role in roles
            if role.role_id != "coordinator" and role.write_policy == "workspace"
        }
    except ValidationFailure as exc:
        diagnostics.extend(exc.diagnostics)
        allowed_roles = set(ROLE_IDS) - {"coordinator"}
        writable_roles = {"implementer", "ops"}
    for manifest in sorted(run_root.glob("*/run.toml")):
        diagnostics.extend(validate_run(manifest, config, allowed_roles, writable_roles))
    return diagnostics


def load_run_model_preset(root: Path, config: TeamConfig, slug: str) -> str:
    if not _SLUG.fullmatch(slug):
        raise ValidationFailure([
            Diagnostic("run", "must contain lowercase letters, digits, and single hyphens", code="format")
        ])
    run_root = (root / config.workflow.run_root).resolve()
    manifest = (run_root / slug / "run.toml").resolve()
    if run_root not in manifest.parents:
        raise ValidationFailure([Diagnostic("run", "run path escapes configured run root", code="path")])
    from agent_team.config import load_roles

    roles = load_roles(config, root)
    diagnostics = validate_run(
        manifest,
        config,
        {role.role_id for role in roles if role.role_id != "coordinator"},
        {
            role.role_id for role in roles
            if role.role_id != "coordinator" and role.write_policy == "workspace"
        },
    )
    errors = [item for item in diagnostics if item.severity == "error"]
    if errors:
        raise ValidationFailure(errors)
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    return data["model_preset"]
