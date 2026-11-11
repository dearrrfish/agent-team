from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from agent_team.adapters import _mapped_role
from agent_team.config import load_roles, resolve_target_profile
from agent_team.models import TARGETS, RoleDefinition, TeamConfig
from agent_team.recovery import discover_runs, select_run
from agent_team.run_state import fail, prepare_review
from agent_team.worktrees import sync_run_artifacts


@dataclass(frozen=True)
class DispatchRequest:
    root: Path
    config: TeamConfig
    slug: str
    role_id: str = "implementer"
    task_id: str | None = None
    runner: str | None = None
    model: str | None = None
    instruction: str | None = None
    worktree: bool = False
    timeout: float = 600.0
    dry_run: bool = False


@dataclass(frozen=True)
class DispatchPlan:
    runner: str
    command: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    prompt: str
    report_path: Path
    task_id: str | None
    role_id: str
    worktree_path: Path | None = None
    timeout: float = 600.0


@dataclass(frozen=True)
class DispatchResult:
    success: bool
    returncode: int
    runner: str
    task_id: str | None
    report_path: Path
    report_synced: bool
    stdout: str
    stderr: str
    details: str


def resolve_runner_for_role(role: RoleDefinition, config: TeamConfig, requested_runner: str | None = None) -> str:
    if requested_runner:
        if requested_runner not in TARGETS:
            fail(f"unsupported runner '{requested_runner}'; must be one of {', '.join(TARGETS)}")
        return requested_runner

    if role.runner:
        return role.runner

    if config.enabled_targets:
        return config.enabled_targets[0]

    return "codex"


def sanitize_dispatch_env(
    base_env: dict[str, str],
    target_runner: str,
    slug: str,
    role_id: str,
    task_id: str | None = None,
    max_depth: int = 1,
) -> dict[str, str]:
    """Sanitize environment variables for child runner execution.

    1. Enforces recursion limits (workers must not delegate recursively).
    2. Strips session/harness markers of heterogeneous targets (e.g. CLAUDE_* when running codex).
    3. Strips session IDs of the target itself to guarantee fresh child sessions.
    4. Preserves API credentials (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.) and system paths.
    5. Injects child agent metadata (AGENT_TEAM_ACTIVE_TARGET, AGENT_TEAM_RUNNER, etc.).
    """
    raw_depth = base_env.get("AGENT_TEAM_DISPATCH_DEPTH", "0")
    try:
        depth = int(raw_depth)
    except ValueError:
        depth = 0

    if depth >= max_depth:
        fail(
            f"role '{role_id}' cannot recursively dispatch child agents "
            f"(current dispatch depth {depth} >= limit {max_depth}). "
            "Subagent workers must not delegate recursively."
        )

    env = dict(base_env)

    # Protected credential suffixes: never strip API keys / tokens
    protected_suffixes = (
        "_API_KEY",
        "_KEY",
        "_TOKEN",
        "_SECRET",
        "_CREDENTIALS",
        "_AUTH_TOKEN",
        "_ACCESS_TOKEN",
    )

    def is_protected_auth(key: str) -> bool:
        upper = key.upper()
        return any(upper.endswith(suffix) for suffix in protected_suffixes)

    # 1. Claude markers
    if target_runner != "claude":
        for k in list(env.keys()):
            if k.startswith("CLAUDE_") and not is_protected_auth(k):
                env.pop(k, None)
            elif k.startswith("ANTHROPIC_CLI_"):
                env.pop(k, None)
    else:
        env.pop("CLAUDE_SESSION_ID", None)
        env.pop("CLAUDE_CONVERSATION_ID", None)

    # 2. Pi markers
    if target_runner != "pi":
        for k in list(env.keys()):
            if k.startswith("PI_") and not is_protected_auth(k):
                env.pop(k, None)
    else:
        env.pop("PI_SESSION_ID", None)

    # 3. Codex markers
    if target_runner != "codex":
        for k in list(env.keys()):
            if (
                k.startswith("CODEX_SESSION")
                or k.startswith("CODEX_INTERNAL_")
                or k == "CODEX_SANDBOX"
            ) and not is_protected_auth(k):
                env.pop(k, None)
    else:
        env.pop("CODEX_SESSION", None)
        env.pop("CODEX_SESSION_ID", None)

    # 4. Antigravity markers
    if target_runner != "antigravity":
        for k in list(env.keys()):
            if k.startswith("ANTIGRAVITY_") and not is_protected_auth(k):
                env.pop(k, None)
    else:
        env.pop("ANTIGRAVITY_SESSION_ID", None)

    # Injected Agent Team Metadata
    env["AGENT_TEAM_DISPATCH_DEPTH"] = str(depth + 1)
    env["AGENT_TEAM_ACTIVE_TARGET"] = target_runner
    env["AGENT_TEAM_RUNNER"] = target_runner
    env["AGENT_TEAM_RUN_SLUG"] = slug
    env["AGENT_TEAM_ROLE_ID"] = role_id
    if task_id:
        env["AGENT_TEAM_TASK_ID"] = task_id
    else:
        env.pop("AGENT_TEAM_TASK_ID", None)

    return env


def build_dispatch_plan(
    req: DispatchRequest,
    base_env: dict[str, str] | None = None,
) -> DispatchPlan:
    candidate, _ = select_run(discover_runs(req.root, req.config), req.root, slug=req.slug)
    if candidate is None or candidate.errors:
        fail(f"run '{req.slug}' cannot be read safely")
    run_dir = candidate.path.parent
    manifest = candidate.manifest

    roles = {r.role_id: r for r in load_roles(req.config, req.root)}
    if req.role_id not in roles:
        fail(f"role '{req.role_id}' is unknown; available roles: {', '.join(sorted(roles))}")
    role = roles[req.role_id]

    runner = resolve_runner_for_role(role, req.config, req.runner)

    # Resolve task details if provided
    task_info: dict | None = None
    tasks = manifest.get("tasks", []) if isinstance(manifest.get("tasks"), list) else []
    if req.task_id:
        for t in tasks:
            if isinstance(t, dict) and t.get("id") == req.task_id:
                task_info = t
                break
        if task_info:
            deps = task_info.get("deps", [])
            if isinstance(deps, list):
                all_tasks = {t.get("id"): t for t in tasks if isinstance(t, dict)}
                for dep_id in deps:
                    dep_t = all_tasks.get(dep_id)
                    if dep_t is None or dep_t.get("status") != "complete":
                        fail(f"task '{req.task_id}' dependency '{dep_id}' is not complete")

    # Resolve report path
    if task_info:
        report_rel = task_info.get("report") or f"reports/{req.task_id}.md"
        report_path = (run_dir / report_rel).resolve()
    elif req.role_id == "reviewer":
        report_path = (run_dir / "review.md").resolve()
    elif req.task_id:
        report_path = (run_dir / f"reports/{req.task_id}.md").resolve()
    else:
        report_path = (run_dir / f"reports/{req.role_id}-adhoc.md").resolve()

    # Worktree path & working directory
    worktree_path: Path | None = None
    cwd = req.root
    if req.worktree:
        wt_name = f"{req.slug}-{req.task_id or req.role_id}"
        worktree_path = (req.root / req.config.workflow.worktree_root / wt_name).resolve()
        cwd = worktree_path

    # Resolve native model if not explicitly specified
    model = req.model
    if not model:
        preset = req.config.default_model_preset
        profile = resolve_target_profile(req.config, runner, req.root)
        if preset in profile.presets:
            mapped_model, _ = _mapped_role(profile, preset, role)
            model = mapped_model

    # Construct prompt
    try:
        report_rel = report_path.relative_to(req.root).as_posix()
    except ValueError:
        report_rel = str(report_path)

    if req.role_id == "reviewer":
        review_packet = prepare_review(req.root, req.config, req.slug)
        prompt_lines = [
            f"# Role: {role.role_id} (Reviewer)",
            role.instructions,
            "",
            review_packet,
            "",
            "## Review Contract",
            f"Save your completed review findings and verdict directly to `{report_rel}`.",
            "Follow the review contract with ## Cycle, ## Verdict, ## Residual risks, and findings.",
        ]
        if req.instruction:
            prompt_lines.append(f"\n## Additional Directives\n{req.instruction}\n")
        prompt = "\n".join(prompt_lines)
    else:
        prompt_lines = [
            f"# Role: {role.role_id}",
            f"{role.description}\n",
            f"## Instructions\n{role.instructions}\n",
            "## Task Context",
            f"- Run: {req.slug}",
            f"- Task ID: {req.task_id or 'adhoc'}",
            f"- Working directory: {cwd}",
            f"- Write policy: {role.write_policy}",
            f"- Report target: {report_rel}\n",
        ]
        if task_info and task_info.get("owned_paths"):
            prompt_lines.append(f"- Owned paths: {', '.join(task_info['owned_paths'])}\n")
        if req.instruction:
            prompt_lines.append(f"## Task Objective\n{req.instruction}\n")
        prompt_lines.extend([
            "## Report Contract",
            f"When you complete your work, you MUST produce an agent-report formatted report and save it to `{report_rel}`.",
            "The report MUST include sections: ## Status, ## Verification, ## Changed files, ## Residual risks.",
        ])
        prompt = "\n".join(prompt_lines)

    # Build command line
    cmd: list[str] = []
    if runner == "codex":
        sandbox = "workspace-write" if role.write_policy == "workspace" else "read-only"
        cmd = ["codex", "exec", "-s", sandbox, "-C", str(cwd)]
        if model:
            cmd.extend(["-m", model])
        if req.worktree:
            cmd.append("--worktree")
        cmd.append(prompt)
    elif runner == "claude":
        cmd = ["claude", "-p", "--permission-mode", "dontAsk"]
        if model:
            cmd.extend(["--model", model])
        if req.worktree:
            cmd.append("--worktree")
        cmd.append(prompt)
    elif runner == "pi":
        cmd = ["pi", "-p"]
        if model:
            cmd.extend(["--model", model])
        if role.write_policy == "deny":
            cmd.extend(["--tools", "read,grep,find,ls"])
        cmd.append(prompt)
    elif runner == "antigravity":
        cmd = ["antigravity", "exec"]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)
    else:
        fail(f"unhandled runner '{runner}'")

    raw_env = dict(os.environ) if base_env is None else dict(base_env)
    env = sanitize_dispatch_env(
        base_env=raw_env,
        target_runner=runner,
        slug=req.slug,
        role_id=req.role_id,
        task_id=req.task_id,
    )

    return DispatchPlan(
        runner=runner,
        command=tuple(cmd),
        cwd=cwd,
        env=env,
        prompt=prompt,
        report_path=report_path,
        task_id=req.task_id,
        role_id=req.role_id,
        worktree_path=worktree_path,
        timeout=req.timeout,
    )


def execute_dispatch(
    root: Path,
    config: TeamConfig,
    slug: str,
    plan: DispatchPlan,
) -> DispatchResult:
    executable_name = plan.command[0]
    executable_path = shutil.which(executable_name)
    if not executable_path:
        return DispatchResult(
            success=False,
            returncode=127,
            runner=plan.runner,
            task_id=plan.task_id,
            report_path=plan.report_path,
            report_synced=False,
            stdout="",
            stderr=(
                f"Runner executable '{executable_name}' not found on PATH. "
                f"Please ensure '{executable_name}' is installed and in your environment PATH."
            ),
            details=f"Executable '{executable_name}' not found",
        )

    # Ensure parent directory of report path exists
    plan.report_path.parent.mkdir(parents=True, exist_ok=True)

    # Create worktree if requested and does not exist
    if plan.worktree_path and not plan.worktree_path.exists():
        plan.worktree_path.parent.mkdir(parents=True, exist_ok=True)
        branch_name = f"dispatch-{slug}-{plan.task_id or plan.role_id}"
        proc = subprocess.run(
            ["git", "worktree", "add", str(plan.worktree_path), "-b", branch_name],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return DispatchResult(
                success=False,
                returncode=proc.returncode,
                runner=plan.runner,
                task_id=plan.task_id,
                report_path=plan.report_path,
                report_synced=False,
                stdout=proc.stdout,
                stderr=proc.stderr,
                details=f"Failed to create worktree at {plan.worktree_path}",
            )

    try:
        proc = subprocess.run(
            list(plan.command),
            cwd=plan.cwd,
            env=dict(plan.env),
            capture_output=True,
            text=True,
            timeout=plan.timeout,
            check=False,
        )
        returncode = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as exc:
        return DispatchResult(
            success=False,
            returncode=124,
            runner=plan.runner,
            task_id=plan.task_id,
            report_path=plan.report_path,
            report_synced=False,
            stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
            stderr=f"Task timed out after {plan.timeout} seconds",
            details="Execution timed out",
        )
    except OSError as exc:
        return DispatchResult(
            success=False,
            returncode=1,
            runner=plan.runner,
            task_id=plan.task_id,
            report_path=plan.report_path,
            report_synced=False,
            stdout="",
            stderr=str(exc),
            details="Execution error",
        )

    # Artifact synchronization from worktree if applicable
    report_synced = False
    if plan.worktree_path and plan.worktree_path.exists():
        synced = sync_run_artifacts(plan.worktree_path, root, slug)
        report_synced = len(synced) > 0

    # Auto-extract report from stdout if report file is missing
    if not plan.report_path.is_file() and stdout:
        if ("## Status" in stdout and "## Verification" in stdout) or ("## Verdict" in stdout):
            plan.report_path.write_text(stdout, encoding="utf-8")
            report_synced = True

    has_report = plan.report_path.is_file()
    success = (returncode == 0) and has_report

    details = "Dispatch completed successfully" if success else (
        f"Runner exited with code {returncode}" if returncode != 0 else "Report file was not produced"
    )

    return DispatchResult(
        success=success,
        returncode=returncode,
        runner=plan.runner,
        task_id=plan.task_id,
        report_path=plan.report_path,
        report_synced=report_synced,
        stdout=stdout,
        stderr=stderr,
        details=details,
    )
