from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from agent_team import __version__
from agent_team.adapters import load_skills, render_target, write_rendered
from agent_team.config import (
    DEFAULT_TEAM_TOML,
    load_roles,
    load_target_profile,
    load_team_config,
    project_root,
    resolve_tier,
)
from agent_team.diagnostics import Diagnostic, ValidationFailure, render_diagnostics
from agent_team.fs import atomic_write
from agent_team.installer import install_files
from agent_team.models import PRESETS, TARGETS, TIERS
from agent_team.runs import init_run, load_run_model_preset, validate_all_runs

_NATIVE_CLIENTS = {
    "codex": "codex",
    "claude": "claude",
    "antigravity": "agy",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-team", description="Portable native agent-team workflow generator")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("init", help="initialize .agent-team/team.toml")

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
    return parser


def _print_failure(exc: ValidationFailure, output_format: str = "text") -> int:
    print(render_diagnostics(exc.diagnostics, output_format), file=sys.stderr)
    return 2


def _init(root: Path) -> int:
    path = root / ".agent-team" / "team.toml"
    if path.exists():
        return _print_failure(ValidationFailure([Diagnostic(str(path), "already exists", code="exists")]))
    atomic_write(path, DEFAULT_TEAM_TOML)
    print(f"initialized {path}")
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
    for target in config.enabled_targets:
        try:
            load_target_profile(target, config.target_profiles[target], root)
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
    mode = "applied" if args.apply else "preview"
    print(f"{mode} for {args.target} ({scope} scope, {model_preset} preset):")
    for action in actions:
        print(f"  {action.action:9} {action.path} — {action.reason}")
    if not args.apply:
        print("preview only; rerun with --apply to write files")
    return 0


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
        if args.command == "doctor":
            return _doctor(root, args.format)
    except ValidationFailure as exc:
        return _print_failure(exc)
    parser.error("unsupported command")
    return 2
