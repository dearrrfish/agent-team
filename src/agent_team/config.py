from __future__ import annotations

import re
import subprocess
import tomllib
from collections.abc import Iterable
from importlib import resources
from pathlib import Path
from typing import Any

from agent_team.diagnostics import Diagnostic, ValidationFailure
from agent_team.models import (
    PRESETS,
    ROLE_IDS,
    TARGETS,
    TIERS,
    InstallConfig,
    RoleDefinition,
    TargetPreset,
    TargetProfile,
    TeamConfig,
    TierConfig,
    WorkflowConfig,
)

DEFAULT_TEAM_TOML = """schema_version = 1
id = "default"
name = "Native agent team"
description = "Portable role-based agent team"
default_tier = "adaptive"
default_model_preset = "balanced"
enabled_targets = ["codex", "claude", "antigravity"]
role_sources = ["builtin:roles"]
skill_sources = ["builtin:skills"]

[target_profiles]
codex = "builtin:codex"
claude = "builtin:claude"
antigravity = "builtin:antigravity"

[workflow]
run_root = ".agent-team/runs"
review_cycle_limit = 2
deep_discovery_default = false
require_worktree_decision = true
persist_agent_reports = true

[tiers.solo]
max_workers = 0
durable_artifacts = false
independent_review = false
write_isolation = "coordinator-only"

[tiers.assisted]
max_workers = 2
durable_artifacts = true
independent_review = false
write_isolation = "serialized"

[tiers.team]
max_workers = 4
durable_artifacts = true
independent_review = true
write_isolation = "file-disjoint-or-worktree"

[install]
default_scope = "project"
overwrite = "refuse"
backups = true
modify_native_settings = false
"""

_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_CAPABILITIES = {"filesystem.read", "filesystem.write", "shell", "docs.read", "web.read"}


def project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".agent-team" / "team.toml").is_file():
            return candidate
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=current,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return current
    if result.returncode == 0:
        return Path(result.stdout.strip()).resolve()
    return current


def _unknown_keys(
    value: dict[str, Any], allowed: Iterable[str], path: str, diagnostics: list[Diagnostic]
) -> None:
    for key in sorted(set(value) - set(allowed)):
        diagnostics.append(Diagnostic(f"{path}.{key}".strip("."), "unknown key", code="unknown-key"))


def _mapping(value: Any, path: str, diagnostics: list[Diagnostic]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    diagnostics.append(Diagnostic(path, "must be a table", code="type"))
    return {}


def _string(value: Any, path: str, diagnostics: list[Diagnostic], default: str = "") -> str:
    if isinstance(value, str):
        return value
    diagnostics.append(Diagnostic(path, "must be a string", code="type"))
    return default


def _boolean(value: Any, path: str, diagnostics: list[Diagnostic], default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    diagnostics.append(Diagnostic(path, "must be a boolean", code="type"))
    return default


def _integer(value: Any, path: str, diagnostics: list[Diagnostic], default: int = 0) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    diagnostics.append(Diagnostic(path, "must be an integer", code="type"))
    return default


def _string_list(value: Any, path: str, diagnostics: list[Diagnostic]) -> tuple[str, ...]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    diagnostics.append(Diagnostic(path, "must be an array of strings", code="type"))
    return ()


def _required(data: dict[str, Any], key: str, path: str, diagnostics: list[Diagnostic]) -> Any:
    if key not in data:
        diagnostics.append(Diagnostic(f"{path}.{key}".strip("."), "required key is missing", code="required"))
    return data.get(key)


def _contained_path(root: Path, raw: str, path: str, diagnostics: list[Diagnostic]) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute():
        diagnostics.append(Diagnostic(path, "must be relative to the project", code="path"))
        return root
    resolved = (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        diagnostics.append(Diagnostic(path, "must stay within the project", code="path"))
        return root
    return candidate


def parse_team_config(data: dict[str, Any], root: Path) -> TeamConfig:
    diagnostics: list[Diagnostic] = []
    allowed = {
        "schema_version", "id", "name", "description", "default_tier",
        "default_model_preset", "enabled_targets", "role_sources", "skill_sources",
        "target_profiles", "workflow", "tiers", "install",
    }
    _unknown_keys(data, allowed, "", diagnostics)
    schema_version = _integer(_required(data, "schema_version", "", diagnostics), "schema_version", diagnostics)
    team_id = _string(_required(data, "id", "", diagnostics), "id", diagnostics)
    name = _string(_required(data, "name", "", diagnostics), "name", diagnostics)
    description = _string(data.get("description", ""), "description", diagnostics)
    default_tier = _string(_required(data, "default_tier", "", diagnostics), "default_tier", diagnostics)
    default_preset = _string(
        _required(data, "default_model_preset", "", diagnostics), "default_model_preset", diagnostics
    )
    enabled_targets = _string_list(
        _required(data, "enabled_targets", "", diagnostics), "enabled_targets", diagnostics
    )
    role_sources = _string_list(_required(data, "role_sources", "", diagnostics), "role_sources", diagnostics)
    skill_sources = _string_list(_required(data, "skill_sources", "", diagnostics), "skill_sources", diagnostics)

    if schema_version != 1:
        diagnostics.append(Diagnostic("schema_version", "only schema version 1 is supported", code="enum"))
    if not _ID.fullmatch(team_id):
        diagnostics.append(Diagnostic("id", "must be a lowercase kebab-case identifier", code="format"))
    if default_tier not in (*TIERS, "adaptive"):
        diagnostics.append(Diagnostic("default_tier", "must be adaptive, solo, assisted, or team", code="enum"))
    if default_preset not in PRESETS:
        diagnostics.append(Diagnostic("default_model_preset", f"must be one of {', '.join(PRESETS)}", code="enum"))
    for index, target in enumerate(enabled_targets):
        if target not in TARGETS:
            diagnostics.append(Diagnostic(f"enabled_targets.{index}", "unsupported target", code="enum"))
    if len(enabled_targets) != len(set(enabled_targets)):
        diagnostics.append(Diagnostic("enabled_targets", "target names must be unique", code="duplicate"))

    profiles_data = _mapping(_required(data, "target_profiles", "", diagnostics), "target_profiles", diagnostics)
    _unknown_keys(profiles_data, TARGETS, "target_profiles", diagnostics)
    target_profiles = {
        key: _string(value, f"target_profiles.{key}", diagnostics)
        for key, value in profiles_data.items()
        if key in TARGETS
    }
    for target in enabled_targets:
        if target not in target_profiles:
            diagnostics.append(Diagnostic(f"target_profiles.{target}", "enabled target needs a profile", code="required"))
    for target, reference in target_profiles.items():
        if not reference.startswith("builtin:"):
            _contained_path(root, reference, f"target_profiles.{target}", diagnostics)

    workflow_data = _mapping(_required(data, "workflow", "", diagnostics), "workflow", diagnostics)
    _unknown_keys(
        workflow_data,
        {"run_root", "review_cycle_limit", "deep_discovery_default", "require_worktree_decision", "persist_agent_reports"},
        "workflow", diagnostics,
    )
    run_root_raw = _string(_required(workflow_data, "run_root", "workflow", diagnostics), "workflow.run_root", diagnostics)
    run_root = _contained_path(root, run_root_raw, "workflow.run_root", diagnostics)
    resolved_run_root = (root / run_root).resolve()
    if resolved_run_root.exists() and not resolved_run_root.is_dir():
        diagnostics.append(Diagnostic(
            "workflow.run_root", "existing run root must be a directory", code="path"
        ))
    review_limit = _integer(
        _required(workflow_data, "review_cycle_limit", "workflow", diagnostics),
        "workflow.review_cycle_limit", diagnostics,
    )
    if not 1 <= review_limit <= 3:
        diagnostics.append(Diagnostic("workflow.review_cycle_limit", "must be between 1 and 3", code="range"))
    workflow = WorkflowConfig(
        run_root=run_root,
        review_cycle_limit=review_limit,
        deep_discovery_default=_boolean(
            _required(workflow_data, "deep_discovery_default", "workflow", diagnostics),
            "workflow.deep_discovery_default", diagnostics,
        ),
        require_worktree_decision=_boolean(
            _required(workflow_data, "require_worktree_decision", "workflow", diagnostics),
            "workflow.require_worktree_decision", diagnostics,
        ),
        persist_agent_reports=_boolean(
            _required(workflow_data, "persist_agent_reports", "workflow", diagnostics),
            "workflow.persist_agent_reports", diagnostics,
        ),
    )

    tiers_data = _mapping(_required(data, "tiers", "", diagnostics), "tiers", diagnostics)
    _unknown_keys(tiers_data, TIERS, "tiers", diagnostics)
    tiers: dict[str, TierConfig] = {}
    isolation = {
        "solo": "coordinator-only",
        "assisted": "serialized",
        "team": "file-disjoint-or-worktree",
    }
    for tier in TIERS:
        item = _mapping(_required(tiers_data, tier, "tiers", diagnostics), f"tiers.{tier}", diagnostics)
        _unknown_keys(item, {"max_workers", "durable_artifacts", "independent_review", "write_isolation"}, f"tiers.{tier}", diagnostics)
        max_workers = _integer(_required(item, "max_workers", f"tiers.{tier}", diagnostics), f"tiers.{tier}.max_workers", diagnostics)
        durable = _boolean(_required(item, "durable_artifacts", f"tiers.{tier}", diagnostics), f"tiers.{tier}.durable_artifacts", diagnostics)
        review = _boolean(_required(item, "independent_review", f"tiers.{tier}", diagnostics), f"tiers.{tier}.independent_review", diagnostics)
        write_isolation = _string(_required(item, "write_isolation", f"tiers.{tier}", diagnostics), f"tiers.{tier}.write_isolation", diagnostics)
        if tier == "solo" and max_workers != 0:
            diagnostics.append(Diagnostic("tiers.solo.max_workers", "must be 0", code="invariant"))
        if tier == "assisted" and not 1 <= max_workers <= 2:
            diagnostics.append(Diagnostic("tiers.assisted.max_workers", "must be between 1 and 2", code="range"))
        if tier == "team" and not 2 <= max_workers <= 8:
            diagnostics.append(Diagnostic("tiers.team.max_workers", "must be between 2 and 8", code="range"))
        if write_isolation != isolation[tier]:
            diagnostics.append(Diagnostic(f"tiers.{tier}.write_isolation", f"must be {isolation[tier]}", code="invariant"))
        if tier == "team" and not review:
            diagnostics.append(Diagnostic("tiers.team.independent_review", "must be true", code="invariant"))
        if tier in {"assisted", "team"} and not durable:
            diagnostics.append(Diagnostic(
                f"tiers.{tier}.durable_artifacts",
                f"{tier} tier requires durable artifacts",
                code="invariant",
            ))
        tiers[tier] = TierConfig(max_workers, durable, review, write_isolation)

    install_data = _mapping(_required(data, "install", "", diagnostics), "install", diagnostics)
    _unknown_keys(install_data, {"default_scope", "overwrite", "backups", "modify_native_settings"}, "install", diagnostics)
    default_scope = _string(_required(install_data, "default_scope", "install", diagnostics), "install.default_scope", diagnostics)
    overwrite = _string(_required(install_data, "overwrite", "install", diagnostics), "install.overwrite", diagnostics)
    backups = _boolean(_required(install_data, "backups", "install", diagnostics), "install.backups", diagnostics)
    modify_settings = _boolean(_required(install_data, "modify_native_settings", "install", diagnostics), "install.modify_native_settings", diagnostics)
    if default_scope not in {"project", "user"}:
        diagnostics.append(Diagnostic("install.default_scope", "must be project or user", code="enum"))
    if overwrite != "refuse":
        diagnostics.append(Diagnostic("install.overwrite", "v1 requires refuse", code="invariant"))
    if modify_settings:
        diagnostics.append(Diagnostic("install.modify_native_settings", "v1 requires false", code="invariant"))

    for source_kind, sources in (("role_sources", role_sources), ("skill_sources", skill_sources)):
        for index, source in enumerate(sources):
            if not source.startswith("builtin:"):
                _contained_path(root, source, f"{source_kind}.{index}", diagnostics)

    if diagnostics:
        raise ValidationFailure(diagnostics)
    return TeamConfig(
        schema_version, team_id, name, description, default_tier, default_preset,
        enabled_targets, role_sources, skill_sources, target_profiles, workflow,
        tiers, InstallConfig(default_scope, overwrite, backups, modify_settings),
    )


def load_team_config(root: Path) -> TeamConfig:
    path = root / ".agent-team" / "team.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValidationFailure([Diagnostic(str(path), "configuration file does not exist", code="missing")])
    except OSError as exc:
        raise ValidationFailure([Diagnostic(str(path), str(exc), code="read")])
    except tomllib.TOMLDecodeError as exc:
        raise ValidationFailure([Diagnostic(str(path), str(exc), code="toml")])
    return parse_team_config(data, root.resolve())


def parse_role(data: dict[str, Any], instructions: str, source: str) -> RoleDefinition:
    diagnostics: list[Diagnostic] = []
    _unknown_keys(
        data,
        {"schema_version", "id", "description", "instructions", "model_class", "effort", "write_policy", "delegation", "max_turns", "report_kind", "capabilities", "activation"},
        source, diagnostics,
    )
    activation = _mapping(_required(data, "activation", source, diagnostics), f"{source}.activation", diagnostics)
    _unknown_keys(activation, {"use_when", "avoid_when"}, f"{source}.activation", diagnostics)
    role_id = _string(_required(data, "id", source, diagnostics), f"{source}.id", diagnostics)
    model_class = _string(_required(data, "model_class", source, diagnostics), f"{source}.model_class", diagnostics)
    effort = _string(_required(data, "effort", source, diagnostics), f"{source}.effort", diagnostics)
    write_policy = _string(_required(data, "write_policy", source, diagnostics), f"{source}.write_policy", diagnostics)
    report_kind = _string(_required(data, "report_kind", source, diagnostics), f"{source}.report_kind", diagnostics)
    capabilities = _string_list(_required(data, "capabilities", source, diagnostics), f"{source}.capabilities", diagnostics)
    max_turns = _integer(_required(data, "max_turns", source, diagnostics), f"{source}.max_turns", diagnostics)
    delegation = _boolean(_required(data, "delegation", source, diagnostics), f"{source}.delegation", diagnostics)
    if data.get("schema_version") != 1:
        diagnostics.append(Diagnostic(f"{source}.schema_version", "only schema version 1 is supported", code="enum"))
    if not _ID.fullmatch(role_id):
        diagnostics.append(Diagnostic(f"{source}.id", "must be a lowercase kebab-case identifier", code="format"))
    if model_class not in {"fast", "balanced", "deep"}:
        diagnostics.append(Diagnostic(f"{source}.model_class", "must be fast, balanced, or deep", code="enum"))
    if effort not in {"low", "medium", "high"}:
        diagnostics.append(Diagnostic(f"{source}.effort", "must be low, medium, or high", code="enum"))
    if write_policy not in {"deny", "workspace"}:
        diagnostics.append(Diagnostic(f"{source}.write_policy", "must be deny or workspace", code="enum"))
    if delegation:
        diagnostics.append(Diagnostic(f"{source}.delegation", "v1 roles cannot delegate", code="invariant"))
    if not 1 <= max_turns <= 64:
        diagnostics.append(Diagnostic(f"{source}.max_turns", "must be between 1 and 64", code="range"))
    if report_kind not in {"agent-report", "review-cycle"}:
        diagnostics.append(Diagnostic(f"{source}.report_kind", "unsupported report kind", code="enum"))
    for capability in capabilities:
        if capability not in _CAPABILITIES:
            diagnostics.append(Diagnostic(f"{source}.capabilities", f"unsupported capability {capability}", code="enum"))
    if write_policy == "deny" and "filesystem.write" in capabilities:
        diagnostics.append(Diagnostic(f"{source}.capabilities", "read-only role cannot request filesystem.write", code="invariant"))
    expected_write_policy = {
        "coordinator": "workspace",
        "explorer": "deny",
        "design-agent": "deny",
        "implementer": "workspace",
        "ops": "workspace",
        "reviewer": "deny",
    }.get(role_id)
    if expected_write_policy is not None and write_policy != expected_write_policy:
        diagnostics.append(Diagnostic(
            f"{source}.write_policy",
            f"built-in role {role_id} requires {expected_write_policy}",
            code="invariant",
        ))
    if role_id == "reviewer" and report_kind != "review-cycle":
        diagnostics.append(Diagnostic(f"{source}.report_kind", "reviewer requires review-cycle", code="invariant"))
    instructions_reference = _string(
        _required(data, "instructions", source, diagnostics), f"{source}.instructions", diagnostics
    )
    description = _string(
        _required(data, "description", source, diagnostics), f"{source}.description", diagnostics
    )
    use_when = _string(
        _required(activation, "use_when", f"{source}.activation", diagnostics),
        f"{source}.activation.use_when", diagnostics,
    )
    avoid_when = _string(
        _required(activation, "avoid_when", f"{source}.activation", diagnostics),
        f"{source}.activation.avoid_when", diagnostics,
    )
    if instructions_reference != "instructions.md":
        diagnostics.append(Diagnostic(f"{source}.instructions", "must be instructions.md", code="invariant"))
    if diagnostics:
        raise ValidationFailure(diagnostics)
    return RoleDefinition(
        role_id=role_id,
        description=description,
        instructions=instructions,
        model_class=model_class,
        effort=effort,
        write_policy=write_policy,
        delegation=delegation,
        max_turns=max_turns,
        report_kind=report_kind,
        capabilities=capabilities,
        use_when=use_when,
        avoid_when=avoid_when,
    )


def load_builtin_roles() -> tuple[RoleDefinition, ...]:
    base = resources.files("agent_team.assets").joinpath("definitions", "roles")
    roles: list[RoleDefinition] = []
    for role_id in ROLE_IDS:
        directory = base.joinpath(role_id)
        data = tomllib.loads(directory.joinpath("role.toml").read_text(encoding="utf-8"))
        instructions = directory.joinpath("instructions.md").read_text(encoding="utf-8")
        roles.append(parse_role(data, instructions, f"roles.{role_id}"))
    return tuple(roles)


def load_roles(config: TeamConfig, root: Path) -> tuple[RoleDefinition, ...]:
    roles: dict[str, RoleDefinition] = {}
    for source in config.role_sources:
        if source == "builtin:roles":
            roles.update((role.role_id, role) for role in load_builtin_roles())
            continue
        directory = (root / source).resolve()
        if not directory.is_dir():
            raise ValidationFailure([Diagnostic(source, "role source directory does not exist", code="missing")])
        for role_file in sorted(directory.glob("*/role.toml")):
            instruction_file = role_file.with_name("instructions.md")
            try:
                data = tomllib.loads(role_file.read_text(encoding="utf-8"))
                instructions = instruction_file.read_text(encoding="utf-8")
            except (OSError, tomllib.TOMLDecodeError) as exc:
                raise ValidationFailure([Diagnostic(str(role_file), str(exc), code="role")])
            role = parse_role(data, instructions, str(role_file))
            if role_file.parent.name != role.role_id:
                raise ValidationFailure([Diagnostic(str(role_file), "role ID must match its directory", code="invariant")])
            roles[role.role_id] = role
    missing = sorted(set(ROLE_IDS) - set(roles))
    if missing:
        raise ValidationFailure([Diagnostic("role_sources", f"missing roles: {', '.join(missing)}", code="required")])
    ordered = [roles[role_id] for role_id in ROLE_IDS]
    ordered.extend(roles[role_id] for role_id in sorted(set(roles) - set(ROLE_IDS)))
    return tuple(ordered)


def parse_target_profile(data: dict[str, Any], source: str) -> TargetProfile:
    diagnostics: list[Diagnostic] = []
    _unknown_keys(
        data,
        {"schema_version", "id", "adapter", "agent_destination", "skill_destination", "models_without_effort", "features", "presets"},
        source, diagnostics,
    )
    profile_id = _string(_required(data, "id", source, diagnostics), f"{source}.id", diagnostics)
    adapter = _string(_required(data, "adapter", source, diagnostics), f"{source}.adapter", diagnostics)
    if data.get("schema_version") != 1:
        diagnostics.append(Diagnostic(f"{source}.schema_version", "only schema version 1 is supported", code="enum"))
    if adapter not in TARGETS or profile_id != adapter:
        diagnostics.append(Diagnostic(f"{source}.adapter", "id and adapter must name the same supported target", code="invariant"))
    features = _mapping(_required(data, "features", source, diagnostics), f"{source}.features", diagnostics)
    _unknown_keys(features, {"supports_effort", "supports_worktree_isolation", "team_runtime"}, f"{source}.features", diagnostics)
    presets_data = _mapping(_required(data, "presets", source, diagnostics), f"{source}.presets", diagnostics)
    _unknown_keys(presets_data, PRESETS, f"{source}.presets", diagnostics)
    presets: dict[str, TargetPreset] = {}
    for preset_name in PRESETS:
        item = _mapping(_required(presets_data, preset_name, f"{source}.presets", diagnostics), f"{source}.presets.{preset_name}", diagnostics)
        _unknown_keys(item, {"coordinator_model", "coordinator_effort", "models", "effort"}, f"{source}.presets.{preset_name}", diagnostics)
        models = _mapping(_required(item, "models", f"{source}.presets.{preset_name}", diagnostics), f"{source}.presets.{preset_name}.models", diagnostics)
        _unknown_keys(models, {"fast", "balanced", "deep"}, f"{source}.presets.{preset_name}.models", diagnostics)
        effort = _mapping(item.get("effort", {}), f"{source}.presets.{preset_name}.effort", diagnostics)
        _unknown_keys(effort, {"low", "medium", "high"}, f"{source}.presets.{preset_name}.effort", diagnostics)
        if set(models) != {"fast", "balanced", "deep"}:
            diagnostics.append(Diagnostic(f"{source}.presets.{preset_name}.models", "must map fast, balanced, and deep", code="required"))
        presets[preset_name] = TargetPreset(
            coordinator_model=_string(_required(item, "coordinator_model", f"{source}.presets.{preset_name}", diagnostics), f"{source}.presets.{preset_name}.coordinator_model", diagnostics),
            coordinator_effort=(
                _string(item["coordinator_effort"], f"{source}.presets.{preset_name}.coordinator_effort", diagnostics)
                if "coordinator_effort" in item else None
            ),
            models={key: _string(value, f"{source}.presets.{preset_name}.models.{key}", diagnostics) for key, value in models.items()},
            effort={key: _string(value, f"{source}.presets.{preset_name}.effort.{key}", diagnostics) for key, value in effort.items()},
        )
    supports_effort = _boolean(_required(features, "supports_effort", f"{source}.features", diagnostics), f"{source}.features.supports_effort", diagnostics)
    supports_worktree_isolation = _boolean(
        _required(features, "supports_worktree_isolation", f"{source}.features", diagnostics),
        f"{source}.features.supports_worktree_isolation", diagnostics,
    )
    models_without_effort = _string_list(
        data.get("models_without_effort", []), f"{source}.models_without_effort", diagnostics
    )
    if supports_effort:
        for preset_name, preset in presets.items():
            if set(preset.effort) != {"low", "medium", "high"}:
                diagnostics.append(Diagnostic(f"{source}.presets.{preset_name}.effort", "effort-capable targets must map low, medium, and high", code="required"))
            if preset.coordinator_effort is None:
                diagnostics.append(Diagnostic(f"{source}.presets.{preset_name}.coordinator_effort", "effort-capable targets must set coordinator effort", code="required"))
    agent_destination = _string(
        _required(data, "agent_destination", source, diagnostics),
        f"{source}.agent_destination", diagnostics,
    )
    skill_destination = _string(
        _required(data, "skill_destination", source, diagnostics),
        f"{source}.skill_destination", diagnostics,
    )
    team_runtime = _string(
        _required(features, "team_runtime", f"{source}.features", diagnostics),
        f"{source}.features.team_runtime", diagnostics,
    )
    if team_runtime != "subagents":
        diagnostics.append(Diagnostic(f"{source}.features.team_runtime", "v1 requires subagents", code="invariant"))
    for destination_key, destination in (
        ("agent_destination", agent_destination), ("skill_destination", skill_destination)
    ):
        candidate = Path(destination)
        if candidate.is_absolute() or ".." in candidate.parts:
            diagnostics.append(Diagnostic(f"{source}.{destination_key}", "must be a contained relative path", code="path"))
    valid_efforts = {"low", "medium", "high", "xhigh", "max", "ultra"}
    for preset_name, preset in presets.items():
        if preset.coordinator_effort is not None and preset.coordinator_effort not in valid_efforts:
            diagnostics.append(Diagnostic(
                f"{source}.presets.{preset_name}.coordinator_effort",
                "unsupported native effort", code="enum",
            ))
        for semantic, native in preset.effort.items():
            if native not in valid_efforts:
                diagnostics.append(Diagnostic(
                    f"{source}.presets.{preset_name}.effort.{semantic}",
                    "unsupported native effort", code="enum",
                ))
    if diagnostics:
        raise ValidationFailure(diagnostics)
    return TargetProfile(
        profile_id=profile_id,
        adapter=adapter,
        agent_destination=agent_destination,
        skill_destination=skill_destination,
        supports_effort=supports_effort,
        supports_worktree_isolation=supports_worktree_isolation,
        team_runtime=team_runtime,
        models_without_effort=models_without_effort,
        presets=presets,
    )


def load_target_profile(target: str, reference: str, root: Path) -> TargetProfile:
    if reference == f"builtin:{target}":
        text = resources.files("agent_team.assets").joinpath("definitions", "targets", f"{target}.toml").read_text(encoding="utf-8")
        return parse_target_profile(tomllib.loads(text), f"targets.{target}")
    path_diagnostics: list[Diagnostic] = []
    path = _contained_path(root.resolve(), reference, f"target_profiles.{target}", path_diagnostics)
    if path_diagnostics:
        raise ValidationFailure(path_diagnostics)
    try:
        profile = parse_target_profile(
            tomllib.loads((root / path).read_text(encoding="utf-8")),
            f"target_profiles.{target}",
        )
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValidationFailure([Diagnostic(f"target_profiles.{target}", str(exc), code="profile")])
    if profile.adapter != target:
        raise ValidationFailure([
            Diagnostic(f"target_profiles.{target}.adapter", "profile adapter must match target", code="invariant")
        ])
    return profile


def resolve_tier(config: TeamConfig, root: Path, requested: str | None) -> str:
    tier = requested or config.default_tier
    if tier != "adaptive":
        return tier
    ignored = {
        ".git", ".agent-team", ".agents", ".claude", ".codex", ".local",
        ".worktrees", ".venv", "build", "dist", "node_modules",
    }
    count = 0
    for path in root.rglob("*"):
        relative_parts = path.relative_to(root).parts
        if path.is_file() and not any(part in ignored for part in relative_parts):
            count += 1
            if count > 200:
                return "team"
    return "solo" if count <= 25 else "assisted"
