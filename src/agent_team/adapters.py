from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from agent_team.config import load_roles, load_target_profile
from agent_team.diagnostics import Diagnostic, ValidationFailure
from agent_team.fs import non_directory_parent
from agent_team.models import RoleDefinition, TargetProfile, TeamConfig
from agent_team.templates import asset_text, render_template


def _quoted_content(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)[1:-1]


def _mapped_role(profile: TargetProfile, preset_name: str, role: RoleDefinition) -> tuple[str, str | None]:
    preset = profile.presets[preset_name]
    if role.role_id == "coordinator":
        model = preset.coordinator_model
        effort = preset.coordinator_effort
    else:
        model = preset.models[role.model_class]
        effort = preset.effort.get(role.effort) if profile.supports_effort else None
    if model in profile.models_without_effort:
        effort = None
    return model, effort


def _tools(role: RoleDefinition, target: str) -> str:
    readable = "filesystem.read" in role.capabilities
    writable = "filesystem.write" in role.capabilities
    shell = "shell" in role.capabilities
    if target == "claude":
        tools: list[str] = []
        if readable:
            tools.extend(["Read", "Glob", "Grep"])
        if writable:
            tools.extend(["Edit", "Write"])
        if shell:
            tools.append("Bash")
        if "web.read" in role.capabilities:
            tools.extend(["WebFetch", "WebSearch"])
        return json.dumps(list(dict.fromkeys(tools)))
    tools = []
    if readable:
        tools.append("read")
    if writable:
        tools.append("write")
    if shell:
        tools.append("shell")
    if "web.read" in role.capabilities:
        tools.append("web")
    return json.dumps(tools)


def _render_agent(target: str, role: RoleDefinition, profile: TargetProfile, preset_name: str) -> str:
    # VERIFY: Exercise native agent discovery when noninteractive validators are
    # available; Antigravity CLI is not installed in the current environment.
    model, effort = _mapped_role(profile, preset_name, role)
    description = (
        f"{role.description} Use when: {role.use_when} Avoid when: {role.avoid_when}"
    )
    instructions = role.instructions.rstrip() + (
        "\n\n# Portable runtime contract\n\n"
        f"- Finish within at most {role.max_turns} turns.\n"
        f"- Return results using the `{role.report_kind}` report contract.\n"
        f"- Use only these declared capabilities: {', '.join(role.capabilities)}.\n"
        "- Do not delegate to another agent.\n"
    )
    if profile.supports_worktree_isolation:
        instructions += (
            f"- The `{target}` target supports worktree isolation for parallel writers.\n"
        )
    else:
        instructions += (
            f"- The `{target}` target does not support worktree isolation; use "
            "file-disjoint ownership for parallel writers.\n"
        )
    if target == "codex":
        template = asset_text("templates", "agents", "codex.toml.tpl")
        return render_template(template, {
            "role_id": role.role_id,
            "description": _quoted_content(description),
            "model": _quoted_content(model),
            "effort_line": f'model_reasoning_effort = "{effort}"\n' if effort else "",
            "sandbox_mode": "read-only" if role.write_policy == "deny" else "workspace-write",
            "instructions": json.dumps(instructions, ensure_ascii=False),
        })
    if target == "claude":
        template = asset_text("templates", "agents", "claude.md.tpl")
        return render_template(template, {
            "role_id": role.role_id,
            "description": json.dumps(description, ensure_ascii=False),
            "model": model,
            "effort_line": f"effort: {effort}\n" if effort else "",
            "tools": _tools(role, target),
            "permission_mode": "plan" if role.write_policy == "deny" else "acceptEdits",
            "instructions": instructions,
        })
    template = asset_text("templates", "agents", "antigravity.md.tpl")
    return render_template(template, {
        "role_id": role.role_id,
        "description": json.dumps(description, ensure_ascii=False),
        "model": model,
        "tools": _tools(role, target),
        "instructions": instructions,
    })


def load_skills(config: TeamConfig, root: Path) -> Iterable[tuple[str, str]]:
    selected: dict[str, str] = {}
    for source in config.skill_sources:
        if source == "builtin:skills":
            for skill_id in ("team-workflow", "team-plan", "team-coordinate", "team-review"):
                selected[skill_id] = asset_text("skills", skill_id, "SKILL.md")
            continue
        directory = (root / source).resolve()
        if not directory.is_dir():
            raise ValidationFailure([Diagnostic(source, "skill source directory does not exist", code="missing")])
        for skill_file in sorted(directory.glob("*/SKILL.md")):
            skill_id = skill_file.parent.name
            if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", skill_id):
                raise ValidationFailure([Diagnostic(str(skill_file), "skill directory must be kebab-case", code="format")])
            try:
                selected[skill_id] = skill_file.read_text(encoding="utf-8")
            except OSError as exc:
                raise ValidationFailure([Diagnostic(str(skill_file), str(exc), code="read")])
    return tuple(sorted(selected.items()))


def render_target(
    target: str,
    config: TeamConfig,
    root: Path,
    model_preset: str | None = None,
) -> dict[PurePosixPath, str]:
    if target not in config.enabled_targets:
        raise ValidationFailure([Diagnostic("target", f"{target} is not enabled", code="disabled")])
    preset_name = model_preset or config.default_model_preset
    profile = load_target_profile(target, config.target_profiles[target], root)
    if preset_name not in profile.presets:
        raise ValidationFailure([Diagnostic(
            "model_preset", f"{preset_name} is not defined by the {target} profile", code="enum"
        )])
    roles = load_roles(config, root)
    output: dict[PurePosixPath, str] = {}
    for role in roles:
        if target == "antigravity":
            relative = PurePosixPath(profile.agent_destination, role.role_id, "agent.md")
        else:
            suffix = ".toml" if target == "codex" else ".md"
            relative = PurePosixPath(profile.agent_destination, f"{role.role_id}{suffix}")
        output[relative] = _render_agent(target, role, profile, preset_name)
    for skill_id, content in load_skills(config, root):
        relative = PurePosixPath(profile.skill_destination, skill_id, "SKILL.md")
        output[relative] = content
    return dict(sorted(output.items(), key=lambda item: str(item[0])))


def write_rendered(output_root: Path, files: dict[PurePosixPath, str]) -> list[Path]:
    from agent_team.fs import atomic_write

    output_root = output_root.resolve()
    planned: list[tuple[Path, str]] = []
    diagnostics: list[Diagnostic] = []
    for relative, content in files.items():
        destination = (output_root / Path(relative)).resolve()
        if destination != output_root and output_root not in destination.parents:
            diagnostics.append(Diagnostic(str(relative), "render path escapes output root", code="path"))
            continue
        blocker = non_directory_parent(output_root, destination)
        if blocker is not None:
            diagnostics.append(Diagnostic(
                str(relative), f"parent path is not a directory: {blocker}", code="parent"
            ))
            continue
        if destination.exists():
            if not destination.is_file():
                diagnostics.append(Diagnostic(
                    str(destination), "render destination is not a regular file", code="conflict"
                ))
                continue
            try:
                existing = destination.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                diagnostics.append(Diagnostic(str(destination), str(exc), code="read"))
                continue
            if existing != content:
                diagnostics.append(Diagnostic(
                    str(destination), "refusing to overwrite existing rendered file", code="conflict"
                ))
                continue
        planned.append((destination, content))
    if diagnostics:
        raise ValidationFailure(diagnostics)

    written: list[Path] = []
    for destination, content in planned:
        if not destination.exists():
            atomic_write(destination, content)
        written.append(destination)
    return written
