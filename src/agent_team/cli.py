from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import subprocess
import sys
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
from agent_team.diagnostics import Diagnostic, ValidationFailure, render_diagnostics
from agent_team.fs import atomic_write
from agent_team.installer import install_files
from agent_team.models import PRESETS, ROLE_IDS, TARGETS, TIERS
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
    generate = subcommands.add_parser("generate", help="generate project gitignore and prompt templates")
    generate.add_argument("selectors", nargs="*", help="gitignore,templates (comma or space separated; default both)")

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
    install.add_argument("--target", required=True, help="comma-separated native targets")
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
    show.add_argument("--format", choices=("text", "json", "table"), default="text")
    fetch = model_commands.add_parser("fetch", help="fetch a live model catalog")
    fetch.add_argument("--target", choices=TARGETS, required=True)
    fetch.add_argument("--format", choices=("text", "json", "table"), default="text")
    fetch.add_argument("--timeout", type=float, default=10.0)
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


def _init(root: Path, scope: str | None = None) -> int:
    if scope != "user":
        require_project_context(root)
    path = user_config_root() / "team.toml" if scope == "user" else root / ".agent-team" / "team.toml"
    if path.exists():
        print(f"warning: existing configuration preserved at {path}", file=sys.stderr)
        return 0
    content = user_init_toml() if scope == "user" else project_init_toml(isolated=scope == "project")
    atomic_write(path, content)
    print(f"initialized {path}")
    return 0


def _generate(root: Path, selectors: list[str]) -> int:
    require_project_context(root)
    selected = [part.strip() for value in selectors for part in value.split(",") if part.strip()] or ["gitignore", "templates"]
    unknown = [part for part in selected if part not in {"gitignore", "templates"}]
    if unknown:
        raise ValidationFailure([Diagnostic("generate", f"unknown selector: {part}", code="enum") for part in unknown])
    entries = AGENT_TEAM_GITIGNORE_ENTRIES
    if "gitignore" in selected and (root / ".agent-team" / "team.toml").is_file():
        config = load_team_config(root)
        paths: dict[PurePosixPath, str] = {}
        for target in config.enabled_targets:
            paths.update(render_target(target, config, root, config.default_model_preset, "project"))
        entries += tuple(
            _literal_gitignore_entry(path) for path in sorted(paths)
            if not any(fnmatch.fnmatchcase(path.as_posix(), pattern.rstrip("/") + ("*" if pattern.endswith("/") else ""))
                       for pattern in AGENT_TEAM_GITIGNORE_ENTRIES)
        )
        # Authored definitions may themselves live beneath the generic native
        # patterns. Reopen their directories after the generated output rules.
        source_directories: set[PurePosixPath] = set()
        for scoped_sources, marker in (
            (config.scoped_role_sources, "role.toml"),
            (config.scoped_skill_sources, "SKILL.md"),
        ):
            for source_root, reference in scoped_sources:
                if source_root.resolve() == root.resolve() and not reference.startswith("builtin:"):
                    source = (source_root / reference).resolve()
                    if source == root.resolve():
                        source_directories.update(
                            PurePosixPath(path.parent.relative_to(root.resolve()).as_posix())
                            for path in source.glob(f"*/{marker}")
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
    if "templates" in selected:
        templates = _upsert_prompt_templates(root)
        print(f"upserted {len(templates)} prompt templates")
    if "gitignore" in selected:
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
        return _install(root, args)
    target_root = root if scope == "project" else Path.home()
    config_root = root if scope == "project" else user_config_root()
    model_preset = load_run_model_preset(root, config, args.run_slug) if args.run_slug else config.default_model_preset
    project_context = root != Path.home().resolve() and (root / ".agent-team" / "team.toml").is_file()
    backup_root = root / ".agent-team" / "backups" if scope == "project" or project_context else None
    rendered: dict[str, dict[PurePosixPath, str]] = {}
    shared: dict[PurePosixPath, str] = {}
    for target in targets:
        files = render_target(target, config, config_root, model_preset, scope)
        for path, content in files.items():
            if path in shared and shared[path] != content:
                raise ValidationFailure([Diagnostic(str(path), "targets render different content to a shared destination", code="collision")])
            shared[path] = content
        rendered[target] = files
        install_files(target=target, target_root=target_root, files=files, apply=False,
                      force=args.force, backups=config.install.backups, backup_root=backup_root,
                      backup_containment_root=root if backup_root is not None else None,
                      require_backup_root=scope == "user")
    # The union also catches resolved aliases and file/ancestor conflicts that
    # cannot be seen by checking each target's output in isolation.
    install_files(
        target=targets[0], target_root=target_root, files=shared, apply=False,
        force=args.force, backups=config.install.backups, backup_root=backup_root,
        backup_containment_root=root if backup_root is not None else None,
        require_backup_root=scope == "user",
    )
    for target, files in rendered.items():
        actions = install_files(target=target, target_root=target_root, files=files, apply=args.apply,
                                force=args.force, backups=config.install.backups, backup_root=backup_root,
                                backup_containment_root=root if backup_root is not None else None,
                                require_backup_root=scope == "user")
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
    if config.field_origins.get(f"target_profiles.{target}") == "user":
        profile_source = f"user:{profile_source}"
    if override is None:
        return profile_source, profile_source
    prefix = f"model_presets.{target}.{preset}"
    def source(key: str) -> str:
        return f"user:{key}" if config.field_origins.get(key) == "user" else key
    if role.role_id == "coordinator":
        return (
            source(f"{prefix}.coordinator_model") if override.coordinator_model is not None else profile_source,
            source(f"{prefix}.coordinator_effort") if override.coordinator_effort is not None else profile_source,
        )
    return (
        source(f"{prefix}.models.{role.model_class}") if role.model_class in override.models else profile_source,
        source(f"{prefix}.effort.{role.effort}") if role.effort in override.effort else profile_source,
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
            return _init(root, args.scope)
        if args.command == "generate":
            return _generate(root, args.selectors)
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
