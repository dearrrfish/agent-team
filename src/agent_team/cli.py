from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

from agent_team import __version__
from agent_team.adapters import _mapped_role, load_skills, render_target, write_rendered
from agent_team.catalog import fetch_catalog
from agent_team.config import (
    DEFAULT_TEAM_TOML,
    load_roles,
    load_team_config,
    project_root,
    resolve_target_profile,
    resolve_tier,
)
from agent_team.diagnostics import Diagnostic, ValidationFailure, render_diagnostics
from agent_team.fs import atomic_write
from agent_team.installer import install_files
from agent_team.models import PRESETS, TARGETS, TIERS
from agent_team.runs import init_run, load_run_model_preset, validate_all_runs
from agent_team.templates import load_prompt_templates

_NATIVE_CLIENTS = {
    "codex": "codex",
    "claude": "claude",
    "antigravity": "agy",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-team", description="Portable native agent-team workflow generator")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser(
        "init",
        help="initialize project configuration, workflow prompt templates, and gitignore",
    )

    validate = subcommands.add_parser("validate", help="validate project configuration and runs")
    validate.add_argument("--format", choices=("text", "json"), default="text")

    run = subcommands.add_parser("run", help="manage durable workflow runs")
    run_commands = run.add_subparsers(dest="run_command", required=True)
    run_init = run_commands.add_parser("init", help="initialize a durable run")
    run_init.add_argument("--slug", required=True)
    run_init.add_argument("--title")
    run_init.add_argument("--tier", choices=(*TIERS, "adaptive"))
    run_init.add_argument("--model-preset", choices=PRESETS)

    render = subcommands.add_parser("render", help="render native agent files into an output directory")
    render.add_argument("--target", choices=TARGETS, required=True)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--run", dest="run_slug", help="use the model preset from this run")

    install = subcommands.add_parser("install", help="preview or apply native agent installation")
    install.add_argument("--target", choices=TARGETS, required=True)
    install.add_argument("--scope", choices=("project", "user"))
    install.add_argument("--apply", action="store_true")
    install.add_argument("--force", action="store_true")
    install.add_argument("--run", dest="run_slug", help="use the model preset from this run")

    doctor = subcommands.add_parser("doctor", help="check the environment and project")
    doctor.add_argument("--format", choices=("text", "json"), default="text")

    models = subcommands.add_parser("models", help="inspect effective routing or live model catalogs")
    model_commands = models.add_subparsers(dest="models_command", required=True)
    show = model_commands.add_parser("show", help="show configured effective model routing")
    show.add_argument("--target", choices=TARGETS)
    selection = show.add_mutually_exclusive_group()
    selection.add_argument("--model-preset", choices=PRESETS)
    selection.add_argument("--run", dest="run_slug", help="use the model preset from this run")
    show.add_argument("--format", choices=("text", "json"), default="text")
    fetch = model_commands.add_parser("fetch", help="fetch a live model catalog")
    fetch.add_argument("--target", choices=TARGETS, required=True)
    fetch.add_argument("--format", choices=("text", "json"), default="text")
    fetch.add_argument("--timeout", type=float, default=10.0)
    return parser


def _print_failure(exc: ValidationFailure, output_format: str = "text") -> int:
    print(render_diagnostics(exc.diagnostics, output_format), file=sys.stderr)
    return 2


AGENT_TEAM_GITIGNORE_ENTRIES: tuple[str, ...] = (
    ".worktrees/",
    ".agent-team/runs/",
    ".agent-team/backups/",
    ".agent-team/install-state.json",
    "/.agent-team/templates/prompts/plan.md",
    "/.agent-team/templates/prompts/coordinate.md",
    "/.agent-team/templates/prompts/review.md",
    "/.agent-team/templates/prompts/discovery.md",
)


def _upsert_prompt_templates(root: Path) -> list[Path]:
    prompts_dir = root / ".agent-team" / "templates" / "prompts"
    templates = load_prompt_templates()
    upserted: list[Path] = []
    for name, content in templates.items():
        destination = prompts_dir / name
        if not destination.exists() or destination.read_text(encoding="utf-8") != content:
            atomic_write(destination, content)
        upserted.append(destination)
    return upserted


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


def _init(root: Path) -> int:
    path = root / ".agent-team" / "team.toml"
    if not path.exists():
        atomic_write(path, DEFAULT_TEAM_TOML)
        print(f"initialized {path}")
    templates = _upsert_prompt_templates(root)
    print(
        f"upserted {len(templates)} prompt templates in "
        f"{root / '.agent-team' / 'templates' / 'prompts'}"
    )
    added_ignores = _upsert_gitignore(root)
    if added_ignores:
        print(f"upserted {len(added_ignores)} entries in {root / '.gitignore'}")
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
    targets_to_resolve = tuple(dict.fromkeys((*config.enabled_targets, *config.model_presets)))
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


def _install(root: Path, args: argparse.Namespace) -> int:
    config = load_team_config(root)
    scope = args.scope or config.install.default_scope
    target_root = root if scope == "project" else Path.home()
    model_preset = (
        load_run_model_preset(root, config, args.run_slug)
        if args.run_slug else config.default_model_preset
    )
    files = render_target(args.target, config, root, model_preset, scope)
    actions = install_files(
        target=args.target,
        target_root=target_root,
        files=files,
        apply=args.apply,
        force=args.force,
        backups=config.install.backups,
    )
    if args.apply and scope == "project":
        managed_paths = set(files)
        managed_paths.update(
            PurePosixPath(action.path) for action in actions if action.action == "stale"
        )
        entries = tuple(_literal_gitignore_entry(path) for path in sorted(managed_paths))
        try:
            _upsert_gitignore(root, entries)
        except OSError as exc:
            raise ValidationFailure([Diagnostic(
                ".gitignore",
                f"native files were installed but ignore rules could not be updated: {exc}; "
                "rerun the same install --apply command to retry",
                code="write",
            )]) from exc
    mode = "applied" if args.apply else "preview"
    print(f"{mode} for {args.target} ({scope} scope, {model_preset} preset):")
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
    if override is None:
        return profile_source, profile_source
    prefix = f"model_presets.{target}.{preset}"
    if role.role_id == "coordinator":
        return (
            f"{prefix}.coordinator_model" if override.coordinator_model is not None else profile_source,
            f"{prefix}.coordinator_effort" if override.coordinator_effort is not None else profile_source,
        )
    return (
        f"{prefix}.models.{role.model_class}" if role.model_class in override.models else profile_source,
        f"{prefix}.effort.{role.effort}" if role.effort in override.effort else profile_source,
    )


def _effective_routing(root: Path, args: argparse.Namespace) -> dict[str, object]:
    config = load_team_config(root)
    targets = (args.target,) if args.target else config.enabled_targets
    if args.target and args.target not in config.enabled_targets:
        raise ValidationFailure([Diagnostic("target", f"{args.target} is not enabled", code="disabled")])
    preset_name = _model_preset(root, config, args)
    roles = load_roles(config, root)
    output: list[dict[str, object]] = []
    for target in targets:
        profile = resolve_target_profile(config, target, root)
        if preset_name not in profile.presets:
            raise ValidationFailure([Diagnostic(
                "model_preset", f"{preset_name} is not defined by the {target} profile", code="enum"
            )])
        resolved_roles: list[dict[str, object]] = []
        for role in roles:
            model, effort = _mapped_role(profile, preset_name, role)
            model_source, effort_source = _source_for_role(config, target, preset_name, role)
            resolved_roles.append({
                "role_id": role.role_id,
                "model_class": "coordinator" if role.role_id == "coordinator" else role.model_class,
                "native_model": model,
                "native_effort": effort,
                "model_source": model_source,
                "effort_source": effort_source if effort is not None else None,
            })
        output.append({"target": target, "preset": preset_name, "roles": resolved_roles})
    return {"schema_version": 1, "kind": "effective-routing", "targets": output}


def _models_show(root: Path, args: argparse.Namespace) -> int:
    payload = _effective_routing(root, args)
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
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
    if args.target not in config.enabled_targets:
        raise ValidationFailure([Diagnostic("target", f"{args.target} is not enabled", code="disabled")])
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
        for model in catalog.models:
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
        for target in config.enabled_targets:
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


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    root = project_root()
    try:
        if args.command == "init":
            return _init(root)
        if args.command == "validate":
            return _validate(root, args.format)
        if args.command == "run":
            return _run_init(root, args)
        if args.command == "render":
            return _render(root, args)
        if args.command == "install":
            return _install(root, args)
        if args.command == "models":
            if args.models_command == "show":
                return _models_show(root, args)
            if args.models_command == "fetch":
                return _models_fetch(root, args)
        if args.command == "doctor":
            return _doctor(root, args.format)
    except ValidationFailure as exc:
        return _print_failure(exc)
    parser.error("unsupported command")
    return 2
