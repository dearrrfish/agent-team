from __future__ import annotations

import re
import subprocess
import tomllib
from collections.abc import Iterable
from dataclasses import replace
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
    RoleOverride,
    TargetPreset,
    TargetPresetOverride,
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
    home = Path.home().resolve()
    user_file = (user_config_root() / "team.toml").resolve()
    for candidate in (current, *current.parents):
        config_file = candidate / ".agent-team" / "team.toml"
        if candidate != home and config_file.resolve() != user_file and config_file.is_file():
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


def require_project_context(root: Path) -> None:
    root = root.resolve()
    user_root = user_config_root().resolve()
    if root == Path.home().resolve() or root == user_root or user_root in root.parents:
        raise ValidationFailure([Diagnostic(
            str(root),
            "project commands require a project directory outside the user configuration; "
            "change to a project, or use --scope user for personal init/install",
            code="scope",
        )])


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


def _nonempty_string(value: Any, path: str, diagnostics: list[Diagnostic]) -> str:
    result = _string(value, path, diagnostics)
    if isinstance(value, str) and not result.strip():
        diagnostics.append(Diagnostic(path, "must not be empty", code="format"))
    if isinstance(value, str) and any(not character.isprintable() for character in result):
        diagnostics.append(Diagnostic(path, "must be a single printable line", code="format"))
    return result


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
        "target_profiles", "model_presets", "workflow", "tiers", "install", "inherit_user_defaults", "roles",
    }
    _unknown_keys(data, allowed, "", diagnostics)
    inherit_user_defaults = _boolean(data.get("inherit_user_defaults", True), "inherit_user_defaults", diagnostics)
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
        if reference.startswith("builtin:") and reference != f"builtin:{target}":
            diagnostics.append(Diagnostic(f"target_profiles.{target}", "unsupported builtin profile", code="enum"))
        if not reference.startswith("builtin:"):
            _contained_path(root, reference, f"target_profiles.{target}", diagnostics)

    model_presets_data = _mapping(data.get("model_presets", {}), "model_presets", diagnostics)
    _unknown_keys(model_presets_data, TARGETS, "model_presets", diagnostics)
    model_presets: dict[str, dict[str, TargetPresetOverride]] = {}
    for target, target_overrides in model_presets_data.items():
        if target not in TARGETS:
            continue
        target_path = f"model_presets.{target}"
        presets_data = _mapping(target_overrides, target_path, diagnostics)
        _unknown_keys(presets_data, PRESETS, target_path, diagnostics)
        parsed_presets: dict[str, TargetPresetOverride] = {}
        for preset_name, preset_override in presets_data.items():
            if preset_name not in PRESETS:
                continue
            preset_path = f"{target_path}.{preset_name}"
            item = _mapping(preset_override, preset_path, diagnostics)
            _unknown_keys(
                item,
                {"coordinator_model", "coordinator_effort", "models", "effort"},
                preset_path,
                diagnostics,
            )
            models = _mapping(item["models"], f"{preset_path}.models", diagnostics) if "models" in item else {}
            _unknown_keys(models, {"fast", "balanced", "deep"}, f"{preset_path}.models", diagnostics)
            effort = _mapping(item["effort"], f"{preset_path}.effort", diagnostics) if "effort" in item else {}
            _unknown_keys(effort, {"low", "medium", "high"}, f"{preset_path}.effort", diagnostics)
            parsed_presets[preset_name] = TargetPresetOverride(
                coordinator_model=(
                    _nonempty_string(item["coordinator_model"], f"{preset_path}.coordinator_model", diagnostics)
                    if "coordinator_model" in item else None
                ),
                coordinator_effort=(
                    _nonempty_string(item["coordinator_effort"], f"{preset_path}.coordinator_effort", diagnostics)
                    if "coordinator_effort" in item else None
                ),
                models={
                    key: _nonempty_string(value, f"{preset_path}.models.{key}", diagnostics)
                    for key, value in models.items()
                    if key in {"fast", "balanced", "deep"}
                },
                effort={
                    key: _nonempty_string(value, f"{preset_path}.effort.{key}", diagnostics)
                    for key, value in effort.items()
                    if key in {"low", "medium", "high"}
                },
            )
        if parsed_presets:
            model_presets[target] = parsed_presets
    for target in model_presets:
        if target not in target_profiles:
            diagnostics.append(Diagnostic(
                f"model_presets.{target}",
                "target needs a configured profile",
                code="required",
            ))

    roles_data = _mapping(data.get("roles", {}), "roles", diagnostics)
    role_overrides: dict[str, RoleOverride] = {}
    target_role_overrides: dict[str, dict[str, RoleOverride]] = {}

    def parse_override(item: dict[str, Any], path: str) -> RoleOverride:
        values: dict[str, str] = {}
        for key, allowed_values in (
            ("model_class", ("fast", "balanced", "deep")),
            ("effort", ("low", "medium", "high")),
        ):
            if key in item:
                value = _string(item[key], f"{path}.{key}", diagnostics)
                if value not in allowed_values:
                    diagnostics.append(Diagnostic(
                        f"{path}.{key}",
                        f"must be one of {', '.join(allowed_values)}", code="enum",
                    ))
                values[key] = value
        return RoleOverride(**values)

    for role_id, raw_override in roles_data.items():
        role_path = f"roles.{role_id}"
        if not _ID.fullmatch(role_id):
            diagnostics.append(Diagnostic(
                role_path, "must be a lowercase kebab-case identifier", code="format"
            ))
        item = _mapping(raw_override, role_path, diagnostics)
        _unknown_keys(item, {"model_class", "effort", "targets"}, role_path, diagnostics)
        role_overrides[role_id] = parse_override(item, role_path)
        targets = _mapping(item.get("targets", {}), f"{role_path}.targets", diagnostics)
        _unknown_keys(targets, TARGETS, f"{role_path}.targets", diagnostics)
        for target, raw_target in targets.items():
            target_path = f"{role_path}.targets.{target}"
            target_item = _mapping(raw_target, target_path, diagnostics)
            _unknown_keys(target_item, {"model_class", "effort"}, target_path, diagnostics)
            override = parse_override(target_item, target_path)
            if target in TARGETS:
                if target not in target_profiles:
                    diagnostics.append(Diagnostic(
                        target_path, "target needs a configured profile", code="required"
                    ))
                target_role_overrides.setdefault(target, {})[role_id] = override

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
            if source.startswith("builtin:") and source != f"builtin:{source_kind.removesuffix('_sources')}s":
                diagnostics.append(Diagnostic(f"{source_kind}.{index}", "unsupported builtin source", code="enum"))
            if not source.startswith("builtin:"):
                _contained_path(root, source, f"{source_kind}.{index}", diagnostics)

    if diagnostics:
        raise ValidationFailure(diagnostics)
    return TeamConfig(
        schema_version, team_id, name, description, default_tier, default_preset,
        enabled_targets, role_sources, skill_sources, target_profiles, model_presets, workflow,
        tiers, InstallConfig(default_scope, overwrite, backups, modify_settings),
        inherit_user_defaults=inherit_user_defaults,
        role_overrides=role_overrides,
        target_role_overrides=target_role_overrides,
    )


def user_config_root() -> Path:
    return Path.home() / ".agent-team"


def _read_config(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValidationFailure(
            [
                Diagnostic(
                    str(path),
                    "configuration file does not exist; run agent-team init --scope user for user setup or agent-team init for a project",
                    code="missing",
                )
            ]
        )
    except OSError as exc:
        raise ValidationFailure([Diagnostic(str(path), str(exc), code="read")])
    except tomllib.TOMLDecodeError as exc:
        raise ValidationFailure([Diagnostic(str(path), str(exc), code="toml")])


def _merge(base: dict[str, Any], layer: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in layer.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _leaves(data: dict[str, Any], prefix: str = "") -> Iterable[str]:
    for key, value in data.items():
        path = f"{prefix}.{key}".strip(".")
        if isinstance(value, dict):
            yield from _leaves(value, path)
        else:
            yield path


def _layered_config(
    root: Path, layers: list[tuple[str, Path, dict[str, Any]]]
) -> TeamConfig:
    builtin = tomllib.loads(DEFAULT_TEAM_TOML)
    merged = builtin
    origins = {key: "builtin" for key in _leaves(builtin)}
    profile_roots = {target: root for target in TARGETS}
    sources: dict[str, list[tuple[Path, str]]] = {
        "role": [(root, "builtin:roles")],
        "skill": [(root, "builtin:skills")],
    }
    for name, scope_root, data in layers:
        # Validate each explicit layer before a later layer can mask bad values.
        validation_data = _merge(builtin, data)
        workflow = validation_data.get("workflow")
        if isinstance(workflow, dict):
            validation_data["workflow"] = {
                **workflow,
                "run_root": builtin["workflow"]["run_root"],
            }
        parse_team_config(validation_data, scope_root)
        if isinstance(data.get("workflow"), dict) and "run_root" in data["workflow"]:
            parse_team_config(
                _merge(
                    builtin, {"workflow": {"run_root": data["workflow"]["run_root"]}}
                ),
                root,
            )
        merged = _merge(merged, data)
        origins.update({key: name for key in _leaves(data)})
        for target in data.get("target_profiles", {}):
            profile_roots[target] = scope_root
        for kind, references in sources.items():
            for reference in data.get(f"{kind}_sources", []):
                if not reference.startswith("builtin:"):
                    references.append((scope_root, reference))
    # The scoped references have already been checked at their defining root.
    safe = dict(merged)
    safe["target_profiles"] = {
        target: f"builtin:{target}" for target in merged["target_profiles"]
    }
    safe["role_sources"] = ["builtin:roles"]
    safe["skill_sources"] = ["builtin:skills"]
    config = parse_team_config(safe, root)
    return replace(
        config,
        target_profiles=merged["target_profiles"],
        role_sources=tuple(merged["role_sources"]),
        skill_sources=tuple(merged["skill_sources"]),
        field_origins=origins,
        target_profile_roots=profile_roots,
        scoped_role_sources=tuple(sources["role"]),
        scoped_skill_sources=tuple(sources["skill"]),
    )


def load_user_config() -> TeamConfig:
    root = user_config_root().resolve()
    return _layered_config(root, [("user", root, _read_config(root / "team.toml"))])


def load_team_config(root: Path) -> TeamConfig:
    root = root.resolve()
    require_project_context(root)
    project = _read_config(root / ".agent-team" / "team.toml")
    inherit = project.get("inherit_user_defaults", True)
    if not isinstance(inherit, bool):
        raise ValidationFailure(
            [Diagnostic("inherit_user_defaults", "must be a boolean", code="type")]
        )
    layers = []
    user_root = user_config_root().resolve()
    if inherit and (user_root / "team.toml").exists():
        layers.append(("user", user_root, _read_config(user_root / "team.toml")))
    layers.append(("project", root, project))
    return _layered_config(root, layers)


def project_init_toml(isolated: bool = False) -> str:
    if isolated:
        return DEFAULT_TEAM_TOML.replace(
            "schema_version = 1", "schema_version = 1\ninherit_user_defaults = false", 1
        )
    return (
        "# Project exceptions override live user defaults in ~/.agent-team/team.toml.\n"
        "# Set inherit_user_defaults = false to isolate this project.\n"
        "schema_version = 1\n"
        "inherit_user_defaults = true\n"
    )


def user_init_toml() -> str:
    return (
        resources.files("agent_team.assets")
        .joinpath("config", "team.toml")
        .read_text(encoding="utf-8")
    )

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
    if role_id == "coordinator" and not delegation:
        diagnostics.append(Diagnostic(
            f"{source}.delegation", "the coordinator must be able to delegate", code="invariant"
        ))
    elif role_id != "coordinator" and delegation:
        diagnostics.append(Diagnostic(
            f"{source}.delegation", "worker roles cannot delegate", code="invariant"
        ))
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
    elif role_id != "reviewer" and report_kind != "agent-report":
        diagnostics.append(Diagnostic(
            f"{source}.report_kind",
            "non-reviewer roles require agent-report",
            code="invariant",
        ))
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
        source=source,
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


def load_roles(
    config: TeamConfig, root: Path, target: str | None = None,
) -> tuple[RoleDefinition, ...]:
    if target is not None and (target not in TARGETS or target not in config.target_profiles):
        raise ValidationFailure([Diagnostic("target", "target needs a supported configured profile", code="enum")])
    roles: dict[str, RoleDefinition] = {}
    for scope_root, source in config.scoped_role_sources or tuple((root, source) for source in config.role_sources):
        if source == "builtin:roles":
            roles.update((role.role_id, role) for role in load_builtin_roles())
            continue
        directory = (scope_root / source).resolve()
        _ensure_contained(scope_root, directory, source)
        if not directory.is_dir():
            raise ValidationFailure([Diagnostic(source, "role source directory does not exist", code="missing")])
        for role_file in sorted(directory.glob("*/role.toml")):
            instruction_file = role_file.with_name("instructions.md")
            _ensure_contained(scope_root, role_file, str(role_file))
            _ensure_contained(scope_root, instruction_file, str(instruction_file))
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
    bindings = [("roles", config.role_overrides)]
    bindings.extend(
        (f"targets.{bound_target}", overrides)
        for bound_target, overrides in config.target_role_overrides.items()
    )
    diagnostics = []
    for binding, overrides in bindings:
        for role_id in sorted(set(overrides) - set(roles)):
            path = (f"roles.{role_id}" if binding == "roles"
                    else f"roles.{role_id}.{binding}")
            diagnostics.append(Diagnostic(path, "override names an unknown role", code="unknown-role"))
    if diagnostics:
        raise ValidationFailure(diagnostics)
    overlays = [(config.role_overrides, "")]
    if target is not None:
        overlays.append((config.target_role_overrides.get(target, {}), f".targets.{target}"))
    for overrides, suffix in overlays:
        for role_id, override in overrides.items():
            values = {
                key: value for key in ("model_class", "effort")
                if (value := getattr(override, key)) is not None
            }
            roles[role_id] = replace(
                roles[role_id], **values,
                routing_override_origins={
                    **roles[role_id].routing_override_origins,
                    **{
                        key: config.field_origins.get(f"roles.{role_id}{suffix}.{key}", "project")
                        for key in values
                    },
                },
            )
    ordered = [roles[role_id] for role_id in ROLE_IDS]
    ordered.extend(roles[role_id] for role_id in sorted(set(roles) - set(ROLE_IDS)))
    return tuple(ordered)


def parse_target_profile(data: dict[str, Any], source: str) -> TargetProfile:
    diagnostics: list[Diagnostic] = []
    _unknown_keys(
        data,
        {
            "schema_version", "id", "adapter", "agent_destination",
            "skill_destination", "user_agent_destination",
            "user_skill_destination", "models_without_effort", "features",
            "presets",
        },
        source, diagnostics,
    )
    profile_id = _string(_required(data, "id", source, diagnostics), f"{source}.id", diagnostics)
    adapter = _string(_required(data, "adapter", source, diagnostics), f"{source}.adapter", diagnostics)
    if data.get("schema_version") != 1:
        diagnostics.append(Diagnostic(f"{source}.schema_version", "only schema version 1 is supported", code="enum"))
    if adapter not in TARGETS or profile_id != adapter:
        diagnostics.append(Diagnostic(f"{source}.adapter", "id and adapter must name the same supported target", code="invariant"))
    features = _mapping(_required(data, "features", source, diagnostics), f"{source}.features", diagnostics)
    _unknown_keys(
        features,
        {"supports_effort", "effort_levels", "supports_worktree_isolation", "team_runtime"},
        f"{source}.features",
        diagnostics,
    )
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
    effort_levels = _string_list(
        _required(features, "effort_levels", f"{source}.features", diagnostics),
        f"{source}.features.effort_levels",
        diagnostics,
    )
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
    user_agent_destination = _string(
        _required(data, "user_agent_destination", source, diagnostics),
        f"{source}.user_agent_destination", diagnostics,
    )
    user_skill_destination = _string(
        _required(data, "user_skill_destination", source, diagnostics),
        f"{source}.user_skill_destination", diagnostics,
    )
    team_runtime = _string(
        _required(features, "team_runtime", f"{source}.features", diagnostics),
        f"{source}.features.team_runtime", diagnostics,
    )
    if team_runtime != "subagents":
        diagnostics.append(Diagnostic(f"{source}.features.team_runtime", "v1 requires subagents", code="invariant"))
    for destination_key, destination in (
        ("agent_destination", agent_destination),
        ("skill_destination", skill_destination),
        ("user_agent_destination", user_agent_destination),
        ("user_skill_destination", user_skill_destination),
    ):
        candidate = Path(destination)
        if not destination or candidate.is_absolute() or ".." in candidate.parts:
            diagnostics.append(Diagnostic(f"{source}.{destination_key}", "must be a contained relative path", code="path"))
    valid_efforts = {"low", "medium", "high", "xhigh", "max", "ultra"}
    if len(effort_levels) != len(set(effort_levels)):
        diagnostics.append(Diagnostic(
            f"{source}.features.effort_levels", "effort levels must be unique", code="duplicate"
        ))
    for effort_level in effort_levels:
        if effort_level not in valid_efforts:
            diagnostics.append(Diagnostic(
                f"{source}.features.effort_levels",
                f"unsupported native effort {effort_level}",
                code="enum",
            ))
    if supports_effort and not effort_levels:
        diagnostics.append(Diagnostic(
            f"{source}.features.effort_levels",
            "effort-capable targets must declare native effort levels",
            code="required",
        ))
    if not supports_effort and effort_levels:
        diagnostics.append(Diagnostic(
            f"{source}.features.effort_levels",
            "targets without effort support must declare no effort levels",
            code="invariant",
        ))
    supported_efforts = set(effort_levels)
    for preset_name, preset in presets.items():
        if preset.coordinator_effort is not None and preset.coordinator_effort not in supported_efforts:
            diagnostics.append(Diagnostic(
                f"{source}.presets.{preset_name}.coordinator_effort",
                "unsupported native effort", code="enum",
            ))
        for semantic, native in preset.effort.items():
            if native not in supported_efforts:
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
        user_agent_destination=user_agent_destination,
        user_skill_destination=user_skill_destination,
        supports_effort=supports_effort,
        effort_levels=effort_levels,
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


def resolve_target_profile(config: TeamConfig, target: str, root: Path) -> TargetProfile:
    """Load a target profile and apply the project's sparse preset overrides."""
    if target not in config.target_profiles:
        raise ValidationFailure([
            Diagnostic(f"target_profiles.{target}", "target profile is not configured", code="required")
        ])
    profile = load_target_profile(target, config.target_profiles[target], config.target_profile_roots.get(target, root))
    overrides = config.model_presets.get(target, {})
    if not overrides:
        return profile

    diagnostics: list[Diagnostic] = []
    presets = dict(profile.presets)
    for preset_name, override in overrides.items():
        preset_path = f"model_presets.{target}.{preset_name}"
        base = profile.presets[preset_name]
        if override.coordinator_effort is not None:
            if not profile.supports_effort:
                diagnostics.append(Diagnostic(
                    f"{preset_path}.coordinator_effort",
                    "target does not support effort overrides",
                    code="invariant",
                ))
            elif override.coordinator_effort not in profile.effort_levels:
                diagnostics.append(Diagnostic(
                    f"{preset_path}.coordinator_effort",
                    "unsupported native effort",
                    code="enum",
                ))
        for semantic, native_effort in override.effort.items():
            if not profile.supports_effort:
                diagnostics.append(Diagnostic(
                    f"{preset_path}.effort.{semantic}",
                    "target does not support effort overrides",
                    code="invariant",
                ))
            elif native_effort not in profile.effort_levels:
                diagnostics.append(Diagnostic(
                    f"{preset_path}.effort.{semantic}",
                    "unsupported native effort",
                    code="enum",
                ))
        presets[preset_name] = TargetPreset(
            coordinator_model=(
                override.coordinator_model
                if override.coordinator_model is not None else base.coordinator_model
            ),
            coordinator_effort=(
                override.coordinator_effort
                if override.coordinator_effort is not None else base.coordinator_effort
            ),
            models={**base.models, **override.models},
            effort={**base.effort, **override.effort},
        )
    if diagnostics:
        raise ValidationFailure(diagnostics)
    return replace(profile, presets=presets)


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


def _ensure_contained(root: Path, path: Path, label: str) -> None:
    resolved = path.resolve()
    boundary = root.resolve()
    if resolved != boundary and boundary not in resolved.parents:
        raise ValidationFailure([Diagnostic(label, "must stay within its defining scope", code="path")])
