from __future__ import annotations

import argparse
import difflib
import fnmatch
import json
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from agent_team import __version__
from agent_team.adapters import _mapped_role, load_skills, render_target, write_rendered
from agent_team.catalog import fetch_catalog
from agent_team.config import (
    load_roles,
    load_team_config,
    load_user_config,
    project_init_toml,
    project_root,
    require_project_context,
    resolve_target_profile,
    resolve_tier,
    user_config_root,
    user_init_toml,
)
from agent_team.config_editor import edit_model_presets, edit_roles
from agent_team.diagnostics import Diagnostic, ValidationFailure, render_diagnostics
from agent_team.fs import atomic_write
from agent_team.installer import install_files
from agent_team.models import PRESETS, ROLE_IDS, TARGETS, TIERS
from agent_team.recovery import (
    discover_runs,
    recovery_status,
    render_context,
    select_run,
)
from agent_team.run_state import bind, lease_change, prepare_review, reconcile, verify
from agent_team.runs import init_run, load_run_model_preset, validate_all_runs
from agent_team.templates import (
    load_example_templates,
)

_NATIVE_CLIENTS = {
    "codex": "codex",
    "claude": "claude",
    "antigravity": "agy",
    "pi": "pi",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-team", description="Portable native agent-team workflow generator")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    init = subcommands.add_parser(
        "init", help="initialize user or project configuration only",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Initialize configuration without generating templates or ignore rules.

Default: create a sparse project config that inherits live user defaults.
--scope user: create full annotated ~/.agent-team/team.toml shared by projects.
--scope project: create full isolated project defaults (user inheritance disabled).
Existing configuration is preserved. Native global agents remain discoverable.

Examples:
  agent-team init --scope user
  agent-team install --scope user --target codex,claude,antigravity --apply
  agent-team init
  agent-team generate
  agent-team init --scope project""",
    )
    init.add_argument("--scope", choices=("user", "project"))
    init.add_argument("--force", "-f", action="store_true", help="overwrite existing configuration")
    init.add_argument("--yes", "-y", action="store_true", help="bypass confirmation prompt")
    init.add_argument("--no-backup", action="store_true", help="do not create a backup when overwriting")
    generate = subcommands.add_parser("generate", help="generate project gitignore and prompt templates")
    generate.add_argument("selectors", nargs="*", help="gitignore,templates (comma or space separated; default both)")
    generate.add_argument("--scope", choices=("user", "project"), help="target scope (user or project)")
    generate.add_argument("--copy", action="store_true", help="copy physical files instead of creating symlinks")

    validate = subcommands.add_parser("validate", help="validate project configuration and runs")
    validate.add_argument("--format", choices=("text", "json"), default="text")

    run = subcommands.add_parser("run", help="manage durable workflow runs")
    run_commands = run.add_subparsers(dest="run_command", required=True)
    run_init = run_commands.add_parser("init", help="initialize a durable run")
    run_init.add_argument("--slug", required=True)
    run_init.add_argument("--title")
    run_init.add_argument("--tier", choices=(*TIERS, "adaptive"))
    run_init.add_argument("--model-preset", choices=PRESETS)

    lease = run_commands.add_parser("lease", help="claim or release observed worker ownership")
    lease_commands = lease.add_subparsers(dest="lease_command", required=True)
    for name in ("claim", "release"):
        action = lease_commands.add_parser(name)
        action.add_argument("--slug", required=True)
        action.add_argument("--task", required=True)
        if name == "claim":
            action.add_argument("--owner", required=True)
            action.add_argument("--owned-path", action="append", required=True)
        else:
            action.add_argument("--token", required=True)
    check = run_commands.add_parser("verify", help="execute a check and record workspace-bound evidence")
    check.add_argument("--slug", required=True)
    check.add_argument("--producer", required=True)
    check.add_argument("--cwd", default=".")
    check.add_argument("check_command", nargs=argparse.REMAINDER)
    reconcile_command = run_commands.add_parser("reconcile", help="preview or apply effective run policy")
    reconcile_command.add_argument("--slug", required=True)
    reconcile_command.add_argument("--apply", action="store_true")
    prepare_review_command = run_commands.add_parser(
        "prepare-review",
        help="assemble a workspace-bound review packet for the next or specified review cycle",
    )
    prepare_review_command.add_argument("--slug", required=True)
    prepare_review_command.add_argument("--cycle", type=int)
    prepare_review_command.add_argument("--base-revision")
    prepare_review_command.add_argument("--format", choices=("markdown", "json"), default="markdown")
    prepare_review_command.add_argument("--output", type=Path)

    resume = subcommands.add_parser(
        "resume", help="inspect durable runs without changing files",
        description="Read-only recovery. Examples: agent-team resume; "
                    "agent-team resume status --json; agent-team resume context --slug my-run",
    )
    resume.add_argument("--slug")
    resume.add_argument("--json", action="store_true")
    resume.add_argument("--session-id")
    resume_commands = resume.add_subparsers(dest="resume_command")
    for name in ("status", "context"):
        command = resume_commands.add_parser(name, help=f"show recovery {name} (read-only)")
        command.add_argument("--slug", default=argparse.SUPPRESS)
        command.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        command.add_argument("--session-id", default=argparse.SUPPRESS)

    hook = resume_commands.add_parser("hook", help="internal compact hook entry")
    hook.add_argument("hook_action", choices=("precompact", "session-start",
                                              "antigravity-session-start",
                                              "antigravity-global-session-start"))
    hook.add_argument("--fail-closed", action="store_true")
    hooks = resume_commands.add_parser(
        "hooks", help="preview, manage, or reconcile optional client hooks")
    operation = hooks.add_mutually_exclusive_group(required=True)
    operation.add_argument("--print", dest="print_hooks", action="store_true")
    operation.add_argument("--install", action="store_true")
    operation.add_argument("--remove", action="store_true")
    operation.add_argument("--status", dest="hook_status", action="store_true",
                           help="list hook ownership records and their state")
    operation.add_argument("--reconcile", dest="hook_reconcile", action="store_true",
                           help="preview or apply migration and cleanup of hook state files")
    hooks.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                       help="machine-readable output for --status")
    hooks.add_argument("--apply", action="store_true")
    hooks.add_argument("--fail-closed", action="store_true")
    hooks.add_argument("--target", choices=("claude", "codex", "antigravity"), default="claude",
                       help="client hook target (claude, codex, or antigravity)")
    hooks.add_argument("--hooks-file", default=None,
                       help="project-relative hook settings file (defaults per target)")
    hooks.add_argument("--scope", choices=("project", "user"), default="project",
                       help="hook scope (project; user is only supported for antigravity)")
    hooks.add_argument("--invocation", choices=("auto", "cli", "interpreter"), default="auto",
                       help="hook command invocation strategy (auto, cli, interpreter)")
    hooks.add_argument("--command-prefix", default=None,
                       help="custom command prefix for hook execution")
    binding = resume_commands.add_parser("bind", help="explicitly bind an active run to a session")
    binding.add_argument("--slug", required=True)
    binding.add_argument("--session-id", default=argparse.SUPPRESS)

    render = subcommands.add_parser("render", help="render native agent files into an output directory")
    render.add_argument("--target", choices=TARGETS, required=True)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--run", dest="run_slug", help="use the model preset from this run")

    install = subcommands.add_parser("install", help="preview or apply native agent installation")
    install.add_argument("--target", required=True, help="comma-separated native targets")
    install.add_argument("--scope", choices=("project", "user"))
    install.add_argument("--apply", action="store_true")
    install.add_argument("--force", action="store_true")
    install.add_argument("--diff", action="store_true", help="show diff when files change")
    install.add_argument("--yes", "-y", action="store_true", help="bypass confirmation prompt when --force is used")
    install.add_argument("--no-backup", action="store_true", help="do not create backups when overwriting")
    install.add_argument("--run", dest="run_slug", help="use the model preset from this run")

    doctor = subcommands.add_parser("doctor", help="check the environment and project")
    doctor.add_argument("--format", choices=("text", "json"), default="text")

    config = subcommands.add_parser("config", help="edit configuration interactively")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    presets = config_commands.add_parser("model-presets", help="preview and edit model routing presets")
    presets.add_argument("--scope", choices=("user", "project"), default="project")
    presets.add_argument("--target", help="comma-separated enabled native targets (default installed clients)")
    presets.add_argument("--preset", choices=PRESETS, help="edit one preset (default all three)")
    presets.add_argument("--dry-run", action="store_true")

    roles = config_commands.add_parser("roles", help="preview and edit semantic role routing")
    roles.add_argument("--scope", choices=("user", "project"), default="project")
    roles.add_argument("--role", choices=ROLE_IDS, help="edit one role (default all builtin roles)")
    roles.add_argument("--target", help="comma-separated configured targets (default all enabled targets)")
    roles.add_argument("--dry-run", action="store_true")

    models = subcommands.add_parser("models", help="inspect effective routing or live model catalogs")
    model_commands = models.add_subparsers(dest="models_command", required=True)
    show = model_commands.add_parser("show", help="show configured effective model routing")
    show.add_argument("--target", choices=TARGETS)
    selection = show.add_mutually_exclusive_group()
    selection.add_argument("--model-preset", choices=PRESETS)
    selection.add_argument("--run", dest="run_slug", help="use the model preset from this run")
    show.add_argument("--format", choices=("text", "json", "table"), default="text")
    fetch = model_commands.add_parser("fetch", help="fetch a live model catalog")
    fetch.add_argument("--target", choices=TARGETS, required=True)
    fetch.add_argument("--format", choices=("text", "json", "table"), default="text")
    fetch.add_argument("--timeout", type=float, default=10.0)

    worktree = subcommands.add_parser("worktree", help="manage and safely clean git worktrees")
    worktree_subs = worktree.add_subparsers(dest="worktree_command", required=True)
    wt_list = worktree_subs.add_parser("list", help="list project worktrees and safety status")
    wt_list.add_argument("--slug", help="filter worktrees associated with a specific run slug")
    wt_list.add_argument("--format", choices=("table", "json"), default="table", help="output format (default: table)")

    wt_clean = worktree_subs.add_parser("clean", help="clean safe worktrees and preserve run evidence")
    wt_clean.add_argument("--slug", help="only clean worktrees associated with a specific run slug")
    wt_clean.add_argument("--dry-run", action="store_true", help="preview cleanup actions without deleting")
    wt_clean.add_argument("--force", action="store_true", help="force deletion of unmerged (ahead) worktrees")
    wt_clean.add_argument("--discard-changes", action="store_true", help="force deletion of dirty worktrees with uncommitted changes")
    wt_clean.add_argument("--no-sync", action="store_true", help="skip syncing run evidence back to main repo")

    dispatch = subcommands.add_parser("dispatch", help="dispatch a role or task to a target tool runner")
    dispatch.add_argument("--slug", required=True, help="run slug")
    dispatch.add_argument("--role", default="implementer", help="role to dispatch (default: implementer)")
    dispatch.add_argument("--task", help="task ID (e.g. T-001)")
    dispatch.add_argument("--runner", choices=TARGETS, help="target runner CLI (default: configured role runner or target profile)")
    dispatch.add_argument("--model", help="override model for the runner")
    dispatch.add_argument("--instruction", help="specific instruction or prompt addition")
    dispatch.add_argument("--worktree", action="store_true", help="run task in an isolated git worktree")
    dispatch.add_argument("--dry-run", action="store_true", help="preview command and prompt without execution")
    dispatch.add_argument("--timeout", type=float, default=600.0, help="timeout in seconds (default: 600)")
    dispatch.add_argument("--format", choices=("text", "json"), default="text", help="output format (default: text)")
    return parser


def _print_failure(exc: ValidationFailure, output_format: str = "text") -> int:
    print(render_diagnostics(exc.diagnostics, output_format), file=sys.stderr)
    return 2


AGENT_TEAM_GITIGNORE_ENTRIES: tuple[str, ...] = (
    ".*/skills/team-*/",
    *(f".*/agents/{role}*" for role in ROLE_IDS),
    ".worktrees/",
    ".agent-team/runs/",
    ".agent-team/backups/",
    ".agent-team/install-state.json",
    ".agent-team/sessions/",
    ".agent-team/hooks-state.json",
    ".agent-team/hooks-state-claude.json",
    ".agent-team/hooks-state-codex.json",
    ".agent-team/hooks-state-antigravity.json",
    ".agent-team/state.lock",
    ".claude/settings.local.json",
    ".codex/hooks.json",
    ".agents/hooks.json",
    "/.agent-team/templates/prompt/plan.md",
    "/.agent-team/templates/prompt/coordinate.md",
    "/.agent-team/templates/prompt/review.md",
    "/.agent-team/templates/prompt/discovery.md",
    "/.agent-team/templates/prompts/plan.md",
    "/.agent-team/templates/prompts/coordinate.md",
    "/.agent-team/templates/prompts/review.md",
    "/.agent-team/templates/prompts/discovery.md",
    "/.agent-team/templates/prompt/",
    "/.agent-team/templates/prompts/",
    "/.agent-team/templates/roles/",
    "/.agent-team/templates/profiles/",
    "/.agent-team/templates/role/",
    "/.agent-team/templates/profile/",
    "/.agent-team/templates/review/",
)


def _upsert_templates(
    scope: str = "project",
    root: Path | None = None,
    copy: bool = False,
) -> list[Path]:
    user_root = user_config_root()
    user_templates_dir = user_root / "templates"

    example_templates = load_example_templates()

    # 1. Always ensure canonical physical templates exist in user scope
    user_upserted: list[Path] = []
    can_use_user = True
    try:
        user_templates_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError):
        can_use_user = False
        if scope == "user":
            raise

    if can_use_user:
        for legacy_prompt in ("prompts", "prompt"):
            legacy_dir = user_templates_dir / legacy_prompt
            if legacy_dir.is_symlink() or legacy_dir.is_file():
                legacy_dir.unlink()
            elif legacy_dir.is_dir():
                shutil.rmtree(legacy_dir, ignore_errors=True)

        for rel_path, content in example_templates.items():
            destination = user_templates_dir / rel_path
            if not destination.exists() or destination.read_text(encoding="utf-8") != content:
                atomic_write(destination, content)
            user_upserted.append(destination)

    if scope == "user":
        return user_upserted

    # 2. Project scope: link to user scope templates (default) or copy files
    if root is None:
        raise ValidationFailure([Diagnostic("project", "project root required for project scope", code="context")])

    proj_templates_dir = root / ".agent-team" / "templates"
    proj_upserted: list[Path] = []

    for legacy_prompt in ("prompts", "prompt"):
        legacy_dir = proj_templates_dir / legacy_prompt
        if legacy_dir.is_symlink() or legacy_dir.is_file():
            legacy_dir.unlink()
        elif legacy_dir.is_dir():
            shutil.rmtree(legacy_dir, ignore_errors=True)

    all_templates = dict(example_templates)

    effective_copy = copy or not can_use_user
    for rel_path, content in all_templates.items():
        proj_dest = proj_templates_dir / rel_path
        user_dest = user_templates_dir / rel_path
        if effective_copy:
            if proj_dest.is_symlink():
                proj_dest.unlink()
            if not proj_dest.exists() or proj_dest.read_text(encoding="utf-8") != content:
                atomic_write(proj_dest, content)
        else:
            proj_dest.parent.mkdir(parents=True, exist_ok=True)
            if proj_dest.is_symlink():
                try:
                    if proj_dest.resolve() == user_dest.resolve() and proj_dest.exists():
                        proj_upserted.append(proj_dest)
                        continue
                except OSError:
                    pass
                proj_dest.unlink()
            elif proj_dest.exists():
                proj_dest.unlink()
            proj_dest.symlink_to(user_dest)
        proj_upserted.append(proj_dest)

    return proj_upserted


def _literal_gitignore_entry(path: PurePosixPath) -> str:
    raw = path.as_posix()
    if "\n" in raw or "\r" in raw:
        raise ValidationFailure([Diagnostic(raw, "cannot represent a newline in .gitignore", code="path")])
    return "/" + "".join(f"\\{character}" if character in "\\*?[]" else character for character in raw)


def _upsert_gitignore(
    root: Path, entries: tuple[str, ...] = AGENT_TEAM_GITIGNORE_ENTRIES,
) -> list[str]:
    gitignore_path = root / ".gitignore"
    if not gitignore_path.exists():
        content = "\n".join(entries) + "\n"
        atomic_write(gitignore_path, content)
        return list(entries)

    existing_text = gitignore_path.read_text(encoding="utf-8")
    existing_lines = existing_text.splitlines()
    existing_normalized = {
        line.strip().lstrip("/")
        for line in existing_lines
        if line.strip() and not line.strip().startswith("#")
    }

    missing = [
        entry for entry in entries
        if entry.lstrip("/") not in existing_normalized
        and not (entry.endswith("/") and entry.lstrip("/").rstrip("/") in existing_normalized)
    ]
    if not missing:
        return []

    separator = "" if not existing_text or existing_text.endswith("\n") else "\n"
    new_text = existing_text + separator + "\n".join(missing) + "\n"
    atomic_write(gitignore_path, new_text)
    return missing


def _init(
    root: Path,
    scope: str | None = None,
    force: bool = False,
    yes: bool = False,
    no_backup: bool = False,
    input_func: object = input,
) -> int:
    if scope != "user":
        require_project_context(root)
    path = user_config_root() / "team.toml" if scope == "user" else root / ".agent-team" / "team.toml"
    content = user_init_toml() if scope == "user" else project_init_toml(isolated=scope == "project")
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing != content:
            diff_lines = list(difflib.unified_diff(
                existing.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            ))
            if diff_lines:
                sys.stdout.writelines(diff_lines)
        if not force:
            print(f"warning: existing configuration preserved at {path}", file=sys.stderr)
            return 0
        if not yes:
            try:
                response = input_func(f"Overwrite existing configuration at {path}? [y/N]: ")
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.", file=sys.stderr)
                return 1
            if response.strip().lower() not in {"y", "yes"}:
                print("Aborted.", file=sys.stderr)
                return 1
        if not no_backup:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_path = path.parent / f".backup_{timestamp}"
            backup_path.write_text(existing, encoding="utf-8")
            print(f"backup created at {backup_path}")
    atomic_write(path, content)
    print(f"initialized {path}")
    return 0


def _generate(
    root: Path | None,
    selectors: list[str],
    scope: str | None = None,
    copy: bool = False,
) -> int:
    selected = [part.strip() for value in selectors for part in value.split(",") if part.strip()] or ["gitignore", "templates"]
    normalized = ["templates" if part in {"template", "templates"} else part for part in selected]
    unknown = [part for part in normalized if part not in {"gitignore", "templates"}]
    if unknown:
        raise ValidationFailure([Diagnostic("generate", f"unknown selector: {part}", code="enum") for part in unknown])

    effective_scope = scope or "project"
    if effective_scope == "user":
        explicit_selectors = [part.strip() for value in selectors for part in value.split(",") if part.strip()]
        if "gitignore" in explicit_selectors:
            raise ValidationFailure([Diagnostic("generate", "gitignore is only supported in project scope", code="context")])
        if "templates" in normalized:
            templates = _upsert_templates(scope="user")
            print(f"upserted {len(templates)} templates in user scope ({user_config_root() / 'templates'})")
        return 0

    require_project_context(root)
    assert root is not None
    entries = AGENT_TEAM_GITIGNORE_ENTRIES
    if "gitignore" in normalized:
        config = load_team_config(root)
        paths: dict[PurePosixPath, str] = {}
        for target in TARGETS:
            paths.update(render_target(target, config, root, config.default_model_preset, "project"))
        entries += tuple(
            _literal_gitignore_entry(path) for path in sorted(paths)
            if not any(fnmatch.fnmatchcase(path.as_posix(), pattern.rstrip("/") + ("*" if pattern.endswith("/") else ""))
                       for pattern in AGENT_TEAM_GITIGNORE_ENTRIES)
        )
        # Authored definitions may themselves live beneath the generic native
        # patterns. Reopen their directories after the generated output rules.
        source_directories: set[PurePosixPath] = set()
        for source_root, reference in config.scoped_role_sources:
            if source_root.resolve() == root.resolve() and not reference.startswith("builtin:"):
                source = (source_root / reference).resolve()
                if source == root.resolve():
                    source_directories.update(
                        PurePosixPath(path.parent.relative_to(root.resolve()).as_posix())
                        for path in source.glob("*/role.toml")
                    )
                else:
                    source_directories.add(PurePosixPath(source.relative_to(root.resolve()).as_posix()))
        for directory in sorted(source_directories):
            ancestors = reversed((directory, *directory.parents))
            entries += tuple(
                "!" + _literal_gitignore_entry(parent) + "/"
                for parent in ancestors if parent != PurePosixPath(".")
            )
            entries += ("!" + _literal_gitignore_entry(directory) + "/**",)
        for target, reference in config.target_profiles.items():
            origin = config.target_profile_roots.get(target, root)
            if origin.resolve() != root.resolve() or reference.startswith("builtin:"):
                continue
            profile_path = (origin / reference).resolve().relative_to(root.resolve())
            relative = PurePosixPath(profile_path.as_posix())
            entries += tuple(
                "!" + _literal_gitignore_entry(parent) + "/"
                for parent in reversed(relative.parents) if parent != PurePosixPath(".")
            )
            entries += ("!" + _literal_gitignore_entry(relative),)
    if "templates" in normalized:
        templates = _upsert_templates(scope="project", root=root, copy=copy)
        mode_desc = "copied" if copy else "symlinked to user scope"
        print(f"upserted {len(templates)} templates ({mode_desc})")
    if "gitignore" in normalized:
        added = _upsert_gitignore(root, entries)
        print(f"upserted {len(added)} entries in {root / '.gitignore'}")
    return 0


def _collect_validation(root: Path) -> list[Diagnostic]:
    config = load_team_config(root)
    diagnostics: list[Diagnostic] = []
    try:
        load_roles(config, root)
    except ValidationFailure as exc:
        diagnostics.extend(exc.diagnostics)
    try:
        load_skills(config, root)
    except ValidationFailure as exc:
        diagnostics.extend(exc.diagnostics)
    targets_to_resolve = tuple(dict.fromkeys((*TARGETS, *config.model_presets)))
    for target in targets_to_resolve:
        try:
            resolve_target_profile(config, target, root)
        except ValidationFailure as exc:
            diagnostics.extend(exc.diagnostics)
    diagnostics.extend(validate_all_runs(root, config))
    return diagnostics


def _validate(root: Path, output_format: str) -> int:
    try:
        diagnostics = _collect_validation(root)
    except ValidationFailure as exc:
        diagnostics = list(exc.diagnostics)
    print(render_diagnostics(diagnostics, output_format))
    return 1 if any(item.severity == "error" for item in diagnostics) else 0


def _run_init(root: Path, args: argparse.Namespace) -> int:
    config = load_team_config(root)
    tier = resolve_tier(config, root, args.tier)
    model_preset = args.model_preset or config.default_model_preset
    destination = init_run(root, config, args.slug, args.title, tier, model_preset)
    print(f"initialized {tier} run at {destination}")
    return 0


def _render(root: Path, args: argparse.Namespace) -> int:
    config = load_team_config(root)
    model_preset = (
        load_run_model_preset(root, config, args.run_slug)
        if args.run_slug else config.default_model_preset
    )
    files = render_target(args.target, config, root, model_preset)
    written = write_rendered(args.output, files)
    print(
        f"rendered {len(written)} files for {args.target} "
        f"with {model_preset} preset into {args.output.resolve()}"
    )
    return 0


def _install(root: Path, args: argparse.Namespace, input_func: object = input) -> int:
    targets = args.target.split(",")
    if any(target not in TARGETS for target in targets) or len(set(targets)) != len(targets):
        raise ValidationFailure([Diagnostic("target", "targets must be unique nonempty names: " + ",".join(TARGETS), code="enum")])
    if args.scope == "user":
        if args.run_slug:
            raise ValidationFailure([Diagnostic("run", "--run is unavailable with user scope", code="scope")])
        if not (user_config_root() / "team.toml").is_file():
            raise ValidationFailure([Diagnostic("user", "warning: user configuration is missing; run init --scope user first", code="missing")])
        config = load_user_config()
    else:
        config = load_team_config(root)
    scope = args.scope or config.install.default_scope
    if scope == "user" and args.scope != "user":
        args.scope = "user"
        return _install(root, args, input_func=input_func)
    target_root = root if scope == "project" else Path.home()
    config_root = root if scope == "project" else user_config_root()
    model_preset = load_run_model_preset(root, config, args.run_slug) if args.run_slug else config.default_model_preset
    project_context = root != Path.home().resolve() and (root / ".agent-team" / "team.toml").is_file()
    backup_root = root / ".agent-team" / "backups" if scope == "project" or project_context else None
    force = getattr(args, "force", False)
    yes = getattr(args, "yes", False)
    no_backup = getattr(args, "no_backup", False)
    show_diff = getattr(args, "diff", False)
    backups = False if no_backup else config.install.backups
    pi_status = None
    if "pi" in targets:
        from agent_team.pi_plugins import require_pi_plugins, scan_pi_plugins

        pi_status = scan_pi_plugins(root, scope)
        require_pi_plugins(pi_status, scope)
        print(render_diagnostics(pi_status.diagnostics, "text"))
    rendered: dict[str, dict[PurePosixPath, str]] = {}
    shared: dict[PurePosixPath, str] = {}
    for target in targets:
        files = render_target(target, config, config_root, model_preset, scope, pi_status=pi_status)
        for path, content in files.items():
            if path in shared and shared[path] != content:
                raise ValidationFailure([Diagnostic(str(path), "targets render different content to a shared destination", code="collision")])
            shared[path] = content
        rendered[target] = files

    if show_diff:
        for rel_path, content in shared.items():
            destination = target_root / Path(rel_path)
            if destination.is_file():
                existing = destination.read_text(encoding="utf-8")
                if existing != content:
                    diff_lines = list(difflib.unified_diff(
                        existing.splitlines(keepends=True),
                        content.splitlines(keepends=True),
                        fromfile=f"a/{destination}",
                        tofile=f"b/{destination}",
                    ))
                    if diff_lines:
                        sys.stdout.writelines(diff_lines)

    for target in targets:
        files = rendered[target]
        install_files(target=target, target_root=target_root, files=files, apply=False,
                      force=force, backups=backups, backup_root=backup_root,
                      backup_containment_root=root if backup_root is not None else None,
                      require_backup_root=scope == "user",
                      allow_no_backup=no_backup)
    # The union also catches resolved aliases and file/ancestor conflicts that
    # cannot be seen by checking each target's output in isolation.
    preview_actions = install_files(
        target=targets[0], target_root=target_root, files=shared, apply=False,
        force=force, backups=backups, backup_root=backup_root,
        backup_containment_root=root if backup_root is not None else None,
        require_backup_root=scope == "user",
        allow_no_backup=no_backup,
    )

    has_conflicts = any(action.action in {"conflict", "drift"} for action in preview_actions)
    if has_conflicts and force and not yes and getattr(args, "apply", False):
        try:
            response = input_func("Overwrite conflicting files? [y/N]: ")
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            return 1
        if response.strip().lower() not in {"y", "yes"}:
            print("Aborted.", file=sys.stderr)
            return 1

    for target, files in rendered.items():
        actions = install_files(target=target, target_root=target_root, files=files, apply=getattr(args, "apply", False),
                                force=force, backups=backups, backup_root=backup_root,
                                backup_containment_root=root if backup_root is not None else None,
                                require_backup_root=scope == "user",
                                allow_no_backup=no_backup)
        mode = "applied" if args.apply else "preview"
        print(f"{mode} for {target} ({scope} scope, {model_preset} preset):")
        for action in actions:
            print(f"  {action.action:9} {action.path} — {action.reason}")
    if not args.apply:
        print("preview only; rerun with --apply to write files")
    return 0


def _model_preset(root: Path, config: object, args: argparse.Namespace) -> str:
    if args.run_slug:
        return load_run_model_preset(root, config, args.run_slug)
    return args.model_preset or config.default_model_preset


def _source_for_role(config: object, target: str, preset: str, role: object) -> tuple[str, str | None]:
    override = config.model_presets.get(target, {}).get(preset)
    profile_source = config.target_profiles[target]
    origin = config.field_origins.get(f"target_profiles.{target}")
    if origin in ("user", "ancestor"):
        profile_source = f"{origin}:{profile_source}"
    if override is None:
        return profile_source, profile_source
    prefix = f"model_presets.{target}.{preset}"
    def source(key: str) -> str:
        field_origin = config.field_origins.get(key)
        return f"{field_origin}:{key}" if field_origin in ("user", "ancestor") else key
    if role.role_id == "coordinator" and override.coordinator_model and "model_class" not in role.routing_override_origins:
        model_source = source(f"{prefix}.coordinator_model")
    elif role.model_class in override.models:
        model_source = source(f"{prefix}.models.{role.model_class}")
    else:
        model_source = profile_source

    if role.role_id == "coordinator" and override.coordinator_effort and "effort" not in role.routing_override_origins:
        effort_source = source(f"{prefix}.coordinator_effort")
    elif role.effort in override.effort:
        effort_source = source(f"{prefix}.effort.{role.effort}")
    else:
        effort_source = profile_source
    return model_source, effort_source


def _effective_routing(root: Path, args: argparse.Namespace) -> dict[str, object]:
    config = load_team_config(root)
    targets = (args.target,) if args.target else TARGETS
    if args.target and args.target not in TARGETS:
        raise ValidationFailure([Diagnostic("target", f"{args.target} is not a supported target", code="enum")])
    preset_name = _model_preset(root, config, args)
    output: list[dict[str, object]] = []
    for target in targets:
        roles = load_roles(config, root, target=target)
        profile = resolve_target_profile(config, target, root)
        if preset_name not in profile.presets:
            raise ValidationFailure([Diagnostic(
                "model_preset", f"{preset_name} is not defined by the {target} profile", code="enum"
            )])
        resolved_roles: list[dict[str, object]] = []
        for role in roles:
            model, effort = _mapped_role(profile, preset_name, role)
            model_source, effort_source = _source_for_role(config, target, preset_name, role)
            model_class = role.model_class
            if role.role_id == "coordinator" and "model_class" not in role.routing_override_origins:
                model_class = "coordinator"
            resolved_roles.append({
                "role_id": role.role_id,
                "model_class": model_class,
                "native_model": model,
                "native_effort": effort,
                "model_source": model_source,
                "effort_source": effort_source if effort is not None else None,
            })
        output.append({"target": target, "preset": preset_name, "roles": resolved_roles})
    return {"schema_version": 1, "kind": "effective-routing", "targets": output}


def _print_table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    values = [tuple("none" if value is None else str(value) for value in row) for row in rows]
    widths = [max([len(header), *(len(row[index]) for row in values)]) for index, header in enumerate(headers)]
    print(" | ".join(header.ljust(width) for header, width in zip(headers, widths)))
    print("-+-".join("-" * width for width in widths))
    for row in values:
        print(" | ".join(value.ljust(width) for value, width in zip(row, widths)))


def _models_show(root: Path, args: argparse.Namespace) -> int:
    payload = _effective_routing(root, args)
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.format == "table":
        rows = [(target["target"], target["preset"], role["role_id"], role["model_class"], role["native_model"], role["native_effort"], role["model_source"], role["effort_source"])
                for target in payload["targets"] for role in target["roles"]]
        _print_table(("Target", "Preset", "Role", "Class", "Model", "Effort", "Model source", "Effort source"), rows)
        return 0
    for target in payload["targets"]:
        print(f"{target['target']} ({target['preset']})")
        for role in target["roles"]:
            effort = role["native_effort"] if role["native_effort"] is not None else "none"
            print(
                f"  {role['role_id']}: class={role['model_class']} model={role['native_model']} "
                f"effort={effort} model_source={role['model_source']} "
                f"effort_source={role['effort_source'] or 'none'}"
            )
    return 0


def _models_fetch(root: Path, args: argparse.Namespace) -> int:
    config = load_team_config(root)
    if args.target not in TARGETS:
        raise ValidationFailure([Diagnostic("target", f"{args.target} is not a supported target", code="enum")])
    profile = resolve_target_profile(config, args.target, root)
    try:
        catalog = fetch_catalog(args.target, args.timeout)
    except ValueError as exc:
        raise ValidationFailure([Diagnostic("timeout", str(exc), code="range")]) from exc
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": "live-catalog",
        "target": catalog.target,
        "source": catalog.source,
        "status": catalog.status,
        "models": list(catalog.models),
        "profile_effort_levels": list(profile.effort_levels),
        "profile_effort_source": config.target_profiles[args.target],
    }
    if catalog.message:
        payload["message"] = catalog.message
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{catalog.target}: {catalog.status} via {catalog.source}")
        if catalog.message:
            print(f"  {catalog.message}")
        if args.format == "table":
            _print_table(("Model ID", "Display name", "Effort options", "Effort source"), [
                (model["model_id"], model["display_name"], ",".join(model["effort_options"]) if model["effort_options"] is not None else "not reported", model.get("effort_source"))
                for model in catalog.models
            ])
        for model in catalog.models if args.format != "table" else ():
            effort = model["effort_options"]
            effort_text = ",".join(effort) if effort is not None else "not reported"
            print(f"  {model['model_id']}: {model['display_name']} (effort: {effort_text})")
        levels = ",".join(profile.effort_levels) if profile.effort_levels else "none"
        print(f"  profile effort levels: {levels} ({config.target_profiles[args.target]})")
    return 0 if catalog.status == "ok" else 1


def _doctor(root: Path, output_format: str) -> int:
    diagnostics = [
        Diagnostic("python", f"Python {sys.version.split()[0]}", severity="info", code="ok")
    ]
    git = shutil.which("git")
    diagnostics.append(Diagnostic("git", git or "git was not found", severity="info" if git else "error", code="ok" if git else "missing"))
    try:
        config = load_team_config(root)
        project_diagnostics = _collect_validation(root)
        diagnostics.extend(project_diagnostics)
        if not any(item.severity == "error" for item in project_diagnostics):
            diagnostics.append(Diagnostic("project", f"valid configuration at {root}", severity="info", code="ok"))
        if "pi" in config.enabled_targets or (root / ".pi").exists():
            from agent_team.pi_plugins import require_pi_plugins, scan_pi_plugins

            status = scan_pi_plugins(root)
            diagnostics.extend(status.diagnostics)
            try:
                require_pi_plugins(status, "project")
            except ValidationFailure as exc:
                diagnostics.extend(item for item in exc.diagnostics if item.severity == "error")
        for target in TARGETS:
            command = _NATIVE_CLIENTS[target]
            executable = shutil.which(command)
            if executable is None:
                diagnostics.append(Diagnostic(
                    f"clients.{target}",
                    f"{command} was not found; rendering and installation remain available",
                    severity="warning",
                    code="missing",
                ))
                continue
            try:
                version_result = subprocess.run(
                    [executable, "--version"],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                diagnostics.append(Diagnostic(
                    f"clients.{target}",
                    f"{executable}; version check failed: {exc}",
                    severity="warning",
                    code="version",
                ))
                continue
            version = (version_result.stdout or version_result.stderr).strip().splitlines()
            if version_result.returncode == 0 and version:
                diagnostics.append(Diagnostic(
                    f"clients.{target}",
                    f"{executable} ({version[0]})",
                    severity="info",
                    code="ok",
                ))
            else:
                diagnostics.append(Diagnostic(
                    f"clients.{target}",
                    f"{executable}; --version exited {version_result.returncode}",
                    severity="warning",
                    code="version",
                ))
    except ValidationFailure as exc:
        diagnostics.extend(exc.diagnostics)
    print(render_diagnostics(diagnostics, output_format))
    return 1 if any(item.severity == "error" for item in diagnostics) else 0


def _resume(root: Path, args: argparse.Namespace) -> int:
    require_project_context(root)
    if args.resume_command == "hooks":
        from agent_team.hooks import (
            hook_groups,
            hook_state_payload,
            hook_state_report,
            manage_hooks,
        )

        json_output = getattr(args, "json", False)
        if json_output and not args.hook_status:
            raise ValidationFailure([Diagnostic(
                "json", "--json is only supported with --status", code="usage")])
        if args.hook_status:
            if json_output:
                print(json.dumps(hook_state_payload(root), ensure_ascii=False, indent=2))
            else:
                print(hook_state_report(root))
        elif args.hook_reconcile:
            print(hook_state_report(root, apply=args.apply))
        elif args.print_hooks:
            groups = hook_groups(args.fail_closed, invocation=args.invocation,
                                 command_prefix=args.command_prefix, target=args.target,
                                 scope=args.scope)
            payload = groups if args.target == "antigravity" else {"hooks": groups}
            print(json.dumps(payload, indent=2))
        else:
            print(manage_hooks(root, remove=args.remove, apply=args.apply,
                               fail_closed=args.fail_closed, hooks_file=args.hooks_file,
                               invocation=args.invocation, command_prefix=args.command_prefix,
                               target=args.target, scope=args.scope))
        return 0
    config = load_team_config(root)
    if args.resume_command == "bind":
        print(bind(root, config, args.slug, args.session_id))
        return 0
    candidates = discover_runs(root, config)
    selected, notices = select_run(candidates, root, slug=args.slug, session_id=args.session_id)
    active = [candidate for candidate in candidates if candidate.active]
    payload: dict = {"candidates": [candidate.to_dict() for candidate in candidates],
                     "selected": None, "notices": notices}
    if selected is not None:
        payload["selected"] = recovery_status(selected, root, config)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for notice in notices:
            print(f"warning: {notice}", file=sys.stderr)
        if selected is not None:
            print(render_context(payload["selected"]))
        else:
            print("Multiple active runs; select one with --slug." if active else "No active runs.")
            for candidate in candidates:
                print(f"{candidate.slug}: {candidate.manifest.get('status', 'unknown')} {candidate.path}")
                for error in candidate.errors:
                    print(f"  error: {error}")
    return 3 if selected is None and active else 0


def _worktree(root: Path | None, args: argparse.Namespace) -> int:
    require_project_context(root)
    assert root is not None

    from agent_team.worktrees import (
        WorktreeStatus,
        clean_worktree,
        list_worktrees,
    )

    worktrees = list_worktrees(root)
    if args.slug:
        worktrees = [wt for wt in worktrees if wt.associated_slug == args.slug]

    if args.worktree_command == "list":
        if args.format == "json":
            data = [
                {
                    "path": str(wt.path),
                    "branch": wt.branch,
                    "head": wt.head_commit,
                    "is_main": wt.is_main,
                    "status": wt.status.value,
                    "details": wt.details,
                    "associated_slug": wt.associated_slug,
                }
                for wt in worktrees
            ]
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0

        if not worktrees:
            print("No worktrees found.")
            return 0

        headers = ("Path", "Branch", "Run Slug", "Status", "Details")
        rows = []
        for wt in worktrees:
            try:
                rel = str(wt.path.relative_to(root))
            except ValueError:
                rel = str(wt.path)
            rows.append((
                rel,
                wt.branch or "(detached)",
                wt.associated_slug or "-",
                wt.status.value,
                wt.details,
            ))
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, val in enumerate(row):
                col_widths[i] = max(col_widths[i], len(val))

        header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
        sep_line = "  ".join("-" * col_widths[i] for i in range(len(headers)))
        print(header_line)
        print(sep_line)
        for row in rows:
            print("  ".join(val.ljust(col_widths[i]) for i, val in enumerate(row)))
        return 0

    if args.worktree_command == "clean":
        sync_artifacts = not args.no_sync
        candidates = [wt for wt in worktrees if not wt.is_main]
        if not candidates:
            print("No candidate worktrees to clean.")
            return 0

        any_failed = False
        action_count = 0
        for wt in candidates:
            if wt.status == WorktreeStatus.DIRTY and not args.discard_changes:
                print(f"Skipping dirty worktree {wt.path}: {wt.details} (use --discard-changes to clean)")
                continue
            if wt.status == WorktreeStatus.AHEAD and not args.force:
                print(f"Skipping unmerged worktree {wt.path}: {wt.details} (use --force to clean)")
                continue
            if wt.status == WorktreeStatus.LOCKED and not args.force:
                print(f"Skipping locked worktree {wt.path}: {wt.details} (use --force to clean)")
                continue

            res = clean_worktree(
                root,
                wt,
                force=args.force,
                discard_changes=args.discard_changes,
                sync_artifacts=sync_artifacts,
                dry_run=args.dry_run,
            )
            if res.success:
                action_count += 1
                sync_info = f" (synced {len(res.synced_files)} run artifact(s))" if res.synced_files else ""
                print(f"[{res.action.upper()}] {wt.path}: {res.details}{sync_info}")
            else:
                any_failed = True
                print(f"[FAILED] {wt.path}: {res.details}", file=sys.stderr)

        if args.dry_run:
            print(f"\nDry run complete. {action_count} worktree(s) would be cleaned.")
        else:
            print(f"\nCleanup complete. {action_count} worktree(s) processed.")
        return 1 if any_failed else 0

    return 2


def _dispatch(root: Path, args: argparse.Namespace) -> int:
    require_project_context(root)
    config = load_team_config(root)
    from agent_team.dispatch import (
        DispatchRequest,
        build_dispatch_plan,
        execute_dispatch,
    )

    req = DispatchRequest(
        root=root,
        config=config,
        slug=args.slug,
        role_id=args.role,
        task_id=args.task,
        runner=args.runner,
        model=args.model,
        instruction=args.instruction,
        worktree=args.worktree,
        timeout=args.timeout,
        dry_run=args.dry_run,
    )
    plan = build_dispatch_plan(req)

    if args.dry_run:
        if args.format == "json":
            data = {
                "runner": plan.runner,
                "role": plan.role_id,
                "task": plan.task_id,
                "command": list(plan.command),
                "cwd": str(plan.cwd),
                "report_path": str(plan.report_path),
                "worktree_path": str(plan.worktree_path) if plan.worktree_path else None,
                "timeout": plan.timeout,
                "prompt": plan.prompt,
            }
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(f"Dispatch Plan for Run: {args.slug}")
            print(f"  Role:        {plan.role_id}")
            print(f"  Runner:      {plan.runner}")
            print(f"  Task ID:     {plan.task_id or '(adhoc)'}")
            print(f"  Working Dir: {plan.cwd}")
            print(f"  Report Path: {plan.report_path}")
            if plan.worktree_path:
                print(f"  Worktree:    {plan.worktree_path}")
            cmd_preview = shlex.join(list(plan.command)[:-1]) if len(plan.command) > 1 else plan.command[0]
            print(f"  Command:     {cmd_preview} <prompt>")
            print("\nPrompt Preview:")
            preview = plan.prompt if len(plan.prompt) <= 600 else plan.prompt[:600] + "\n... (truncated)"
            print(preview)
        return 0

    print(f"Dispatching role '{plan.role_id}' to runner '{plan.runner}' (timeout: {plan.timeout}s)...")
    res = execute_dispatch(root, config, args.slug, plan)
    if res.success:
        print(f"Dispatch succeeded: {res.details}")
        print(f"Report saved to: {res.report_path}")
        return 0
    else:
        print(f"Dispatch failed: {res.details}", file=sys.stderr)
        if res.stderr:
            print(f"Error output:\n{res.stderr}", file=sys.stderr)
        return res.returncode if res.returncode != 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:2] == ["resume", "hook"]:
        from agent_team.hooks import run_hook

        try:
            args = parser.parse_args(arguments)
        except SystemExit:
            if arguments[2:3] == ["session-start"]:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                    "additionalContext": "agent-team hook 参数错误；请检查 hooks 配置并暂停写操作。"}}))
                return 0
            return 2 if "--fail-closed" in arguments else 1
        return run_hook(args.hook_action, args.fail_closed)
    args = parser.parse_args(arguments)
    root = project_root()
    try:
        if args.command == "init":
            return _init(root, args.scope, force=args.force, yes=args.yes, no_backup=args.no_backup)
        if args.command == "generate":
            return _generate(root, args.selectors, scope=args.scope, copy=args.copy)
        if args.command == "validate":
            return _validate(root, args.format)
        if args.command == "run":
            if args.run_command == "init":
                return _run_init(root, args)
            require_project_context(root)
            config = load_team_config(root)
            if args.run_command == "lease":
                if args.lease_command == "claim":
                    print(lease_change(root, config, args.slug, args.task,
                                       owner=args.owner, owned_paths=args.owned_path))
                else:
                    print(lease_change(root, config, args.slug, args.task, token=args.token))
                return 0
            if args.run_command == "verify":
                command = args.check_command
                if command[:1] == ["--"]:
                    command = command[1:]
                return verify(root, config, args.slug, command, args.producer, args.cwd)
            if args.run_command == "reconcile":
                print(reconcile(root, config, args.slug, args.apply) or "No policy changes.")
                return 0
            if args.run_command == "prepare-review":
                print(
                    prepare_review(
                        root,
                        config,
                        args.slug,
                        cycle=args.cycle,
                        base_revision=args.base_revision,
                        output_format=args.format,
                        output_path=args.output,
                    ),
                    end="",
                )
                return 0
        if args.command == "resume":
            return _resume(root, args)
        if args.command == "render":
            return _render(root, args)
        if args.command == "install":
            return _install(root, args)
        if args.command == "config":
            if args.config_command == "roles":
                return edit_roles(root, scope=args.scope, role=args.role, target=args.target, dry_run=args.dry_run)
            return edit_model_presets(root, scope=args.scope, target=args.target,
                                      preset=args.preset, dry_run=args.dry_run)
        if args.command == "models":
            if args.models_command == "show":
                return _models_show(root, args)
            if args.models_command == "fetch":
                return _models_fetch(root, args)
        if args.command == "doctor":
            return _doctor(root, args.format)
        if args.command == "worktree":
            return _worktree(root, args)
        if args.command == "dispatch":
            return _dispatch(root, args)
    except ValidationFailure as exc:
        return _print_failure(exc)
    parser.error("unsupported command")
    return 2
