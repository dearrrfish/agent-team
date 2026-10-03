"""Preview-first, scope-isolated interactive model preset editing."""
from __future__ import annotations

import difflib
import os
import shutil
import tempfile
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path
from typing import Any

from agent_team.catalog import CatalogResult, fetch_catalog
from agent_team.config import (
    _layered_config,
    load_roles,
    require_project_context,
    resolve_target_profile,
    user_config_root,
)
from agent_team.diagnostics import Diagnostic, ValidationFailure
from agent_team.fs import atomic_write
from agent_team.models import (
    PRESETS,
    ROLE_IDS,
    TARGETS,
    TargetPreset,
    TargetProfile,
    TeamConfig,
)
from agent_team.toml_edit import upsert_strings

_CLIENTS = {"codex": "codex", "claude": "claude", "antigravity": "agy"}
_CLASSES = ("fast", "balanced", "deep")
_EFFORTS = ("low", "medium", "high")


def _fail(path: str | Path, message: str, code: str = "config-editor") -> ValidationFailure:
    return ValidationFailure([Diagnostic(str(path), message, code=code)])


def _read(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise _fail(path, f"cannot read configuration: {exc}") from exc


def _parse(content: str, path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise _fail(path, str(exc), "toml") from exc


def _safe_destination(path: Path, boundary: Path) -> None:
    if path != boundary and boundary not in path.parents:
        raise _fail(path, "destination escapes selected scope", "path")
    if boundary.is_symlink():
        raise _fail(boundary, "symlink destinations are unsupported", "path")
    for component in (path, *path.parents):
        if component.is_symlink():
            raise _fail(component, "symlink destinations are unsupported", "path")
        if component == boundary:
            break
    if boundary != path.resolve() and boundary not in path.resolve().parents:
        raise _fail(path, "destination escapes selected scope", "path")
    if path.exists() and not path.is_file():
        raise _fail(path, "destination must be a regular file", "path")
    for parent in path.parents:
        if parent.exists() and not parent.is_dir():
            raise _fail(parent, "destination parent must be a directory", "path")
        if parent == boundary:
            break


def select_targets(config: TeamConfig, requested: str | None) -> tuple[str, ...]:
    targets = (
        tuple(item.strip() for item in requested.split(","))
        if requested is not None else
        tuple(target for target in config.enabled_targets if shutil.which(_CLIENTS[target]))
    )
    if not targets:
        raise _fail("targets", "no enabled native clients found on PATH; install a client first")
    if len(set(targets)) != len(targets):
        raise _fail("targets", "target names must be unique")
    for target in targets:
        if target not in TARGETS:
            raise _fail("targets", f"unsupported target {target!r}; choose {', '.join(TARGETS)}")
        if target not in config.enabled_targets or target not in config.target_profiles:
            raise _fail(target, "target must be enabled and have a configured profile")
        if not shutil.which(_CLIENTS[target]):
            raise _fail(target, f"{_CLIENTS[target]} was not found on PATH; install the native client")
    return targets


def _menu(
    label: str, options: tuple[str, ...], default: str | None,
    read: Callable[[str], str], emit: Callable[[str], None],
    names: Mapping[str, str] | None = None,
) -> str:
    if not options:
        raise _fail(label, "no compatible choices; select models with compatible effort support")
    valid_default = default if default in options else None
    emit(label)
    for index, option in enumerate(options, 1):
        display = names.get(option, option) if names else option
        suffix = " (current)" if option == valid_default else ""
        emit(f"  {index}. {option}" + (f" — {display}" if display != option else "") + suffix)
    prompt = f"Choice [current: {valid_default}]: " if valid_default else "Choice (required): "
    while True:
        answer = read(prompt).strip()
        if not answer and valid_default is not None:
            return valid_default
        if answer in options:
            return answer
        if answer.isdecimal() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        emit("Enter a listed number or value" + (", or press Enter to retain current." if valid_default else "."))


def _compatible_efforts(
    profile: TargetProfile, models: tuple[str, ...], catalog: Mapping[str, dict[str, Any]],
    emit: Callable[[str], None], *, coordinator: bool = False,
) -> tuple[str, ...]:
    allowed = set(profile.effort_levels)
    for model in models:
        metadata = catalog[model].get("effort_options")
        if metadata == [] and coordinator:
            raise _fail(model, "catalog reports no effort support; coordinator schema requires effort")
        if model in profile.models_without_effort and not coordinator:
            emit(f"{model}: profile suppresses native effort.")
            continue
        if metadata is None:
            emit(f"{model}: catalog effort metadata unavailable; using profile effort levels.")
        else:
            allowed.intersection_update(metadata)
    return tuple(level for level in profile.effort_levels if level in allowed)


def _choose_preset(
    target: str, name: str, profile: TargetProfile, catalog: CatalogResult,
    read: Callable[[str], str], emit: Callable[[str], None],
) -> TargetPreset:
    old = profile.presets[name]
    metadata = {model["model_id"]: model for model in catalog.models}
    options = tuple(metadata)
    names = {key: value.get("display_name", key) for key, value in metadata.items()}
    prefix = f"{target} / {name}"
    coordinator = _menu(f"{prefix} / coordinator model", options, old.coordinator_model, read, emit, names)
    models = {
        key: _menu(f"{prefix} / {key} model", options, old.models[key], read, emit, names)
        for key in _CLASSES
    }
    if not profile.supports_effort:
        for model in (coordinator, *models.values()):
            choices = metadata[model].get("effort_options")
            if choices:
                raise _fail(model, "model requires effort choices unsupported by the selected profile")
        return TargetPreset(coordinator, None, models, {})
    coordinator_options = _compatible_efforts(profile, (coordinator,), metadata, emit, coordinator=True)
    coordinator_effort = _menu(
        f"{prefix} / coordinator effort", coordinator_options, old.coordinator_effort, read, emit,
    )
    worker_options = _compatible_efforts(profile, tuple(models.values()), metadata, emit)
    efforts = {
        key: _menu(f"{prefix} / shared {key} effort", worker_options, old.effort[key], read, emit)
        for key in _EFFORTS
    }
    return TargetPreset(coordinator, coordinator_effort, models, efforts)


def _leaves(preset: TargetPreset) -> dict[tuple[str, ...], str]:
    values = {("coordinator_model",): preset.coordinator_model}
    if preset.coordinator_effort is not None:
        values[("coordinator_effort",)] = preset.coordinator_effort
    values.update({("models", key): value for key, value in preset.models.items()})
    values.update({("effort", key): value for key, value in preset.effort.items()})
    return values


@dataclass(frozen=True)
class Candidate:
    path: Path
    original: str | None
    content: str
    boundary: Path


def apply_candidates(candidates: tuple[Candidate, ...], snapshots: Mapping[Path, str]) -> None:
    """Preflight all files, then atomically replace each with best-effort rollback."""
    for path, original in snapshots.items():
        if _read(path) != original:
            raise _fail(path, "configuration changed since preview; rerun the command", "conflict")
    for candidate in candidates:
        _safe_destination(candidate.path, candidate.boundary)
        current = _read(candidate.path) if candidate.path.exists() else None
        if current != candidate.original:
            raise _fail(candidate.path, "configuration changed since preview; rerun the command", "conflict")
    attempted: list[Candidate] = []
    modes = {c.path: c.path.stat().st_mode & 0o777 for c in candidates if c.path.exists()}
    try:
        for candidate in candidates:
            _safe_destination(candidate.path, candidate.boundary)
            current = _read(candidate.path) if candidate.path.exists() else None
            if current != candidate.original:
                raise _fail(candidate.path, "configuration changed during save", "conflict")
            # Replacement may commit before an interrupt prevents the call returning.
            attempted.append(candidate)
            atomic_write(candidate.path, candidate.content)
            if candidate.path in modes:
                os.chmod(candidate.path, modes[candidate.path])
    except (OSError, ValidationFailure, KeyboardInterrupt) as exc:
        failures = []
        for candidate in reversed(attempted):
            try:
                _safe_destination(candidate.path, candidate.boundary)
                current = _read(candidate.path) if candidate.path.exists() else None
                if current == candidate.original:
                    continue
                if current != candidate.content:
                    raise _fail(candidate.path, "file changed externally during rollback; preserved external contents", "conflict")
                if candidate.original is None:
                    candidate.path.unlink()
                else:
                    atomic_write(candidate.path, candidate.original)
                    os.chmod(candidate.path, modes[candidate.path])
            except (OSError, ValidationFailure, KeyboardInterrupt) as rollback:
                reason = "recovery interrupted; verify file contents" if isinstance(rollback, KeyboardInterrupt) else str(rollback)
                failures.append(f"{candidate.path}: {reason}")
        details = "; rollback failed: " + "; ".join(failures) if failures else "; earlier writes restored"
        raise _fail("save", f"save failed: {exc}{details}") from exc


def _edit_model_presets(
    root: Path, *, scope: str = "project", target: str | None = None,
    preset: str | None = None, dry_run: bool = False,
    read: Callable[[str], str] | None = None, emit: Callable[[str], None] = print,
) -> int:
    read = read or input
    if scope not in ("project", "user") or (preset is not None and preset not in PRESETS):
        raise _fail("selection", "invalid scope or preset")
    root = root.resolve()
    user_root = user_config_root()
    if scope == "user" and user_root.is_symlink():
        raise _fail(user_root, "symlink destinations are unsupported", "path")
    user_root = user_root.resolve()
    boundary = root if scope == "project" else user_root
    config_path = boundary / ".agent-team" / "team.toml" if scope == "project" else boundary / "team.toml"
    if scope == "project":
        require_project_context(root)
    _safe_destination(config_path, boundary)
    scoped_text = _read(config_path)
    scoped_data = _parse(scoped_text, config_path)
    snapshots = {config_path: scoped_text}
    layers = []
    if scope == "project" and scoped_data.get("inherit_user_defaults", True) and (user_root / "team.toml").exists():
        user_path = user_root / "team.toml"
        snapshots[user_path] = _read(user_path)
        layers.append(("user", user_root, _parse(snapshots[user_path], user_path)))
    layers.append((scope, boundary, scoped_data))
    config = _layered_config(boundary, layers)
    targets = select_targets(config, target)
    profile_sources: dict[str, tuple[Path, str]] = {}
    for name in targets:
        reference = config.target_profiles[name]
        if not reference.startswith("builtin:"):
            path = config.target_profile_roots[name] / reference
            content = _read(path)
            snapshots[path] = content
            profile_sources[name] = (path, content)
    profiles = {name: resolve_target_profile(config, name, boundary) for name in targets}
    for path, original in snapshots.items():
        if _read(path) != original:
            raise _fail(path, "configuration changed while loading; rerun the command", "conflict")
    catalogs = {name: fetch_catalog(name, 10.0) for name in targets}
    for name, catalog in catalogs.items():
        if catalog.status != "ok" or not catalog.models:
            raise _fail(name, f"live model catalog unavailable ({catalog.source}): {catalog.message or catalog.status}; fix discovery/authentication and retry")
    try:
        names = (preset,) if preset else PRESETS
        selected = {
            name: {key: _choose_preset(name, key, profiles[name], catalogs[name], read, emit) for key in names}
            for name in targets
        }
        team_changes: dict[tuple[str, ...], str] = {}
        candidates: list[Candidate] = []
        staged_profiles: dict[str, str] = {}
        for name in targets:
            changed = {
                (key, *leaf): value
                for key, choice in selected[name].items()
                for leaf, value in _leaves(choice).items()
                if _leaves(profiles[name].presets[key]).get(leaf) != value
            }
            if not changed:
                continue
            if name not in profile_sources:
                team_changes.update({("model_presets", name, *leaf): value for leaf, value in changed.items()})
                continue
            path, original = profile_sources[name]
            inherited = config.target_profile_roots[name].resolve() != boundary
            if inherited:
                path = boundary / ".agent-team" / "profiles" / f"{name}.toml"
                _safe_destination(path, boundary)
                if path.exists():
                    raise _fail(path, "project profile copy destination already exists; choose a local profile reference first")
                team_changes[("target_profiles", name)] = path.relative_to(boundary).as_posix()
            _safe_destination(path, boundary)
            content = upsert_strings(original, {("presets", *leaf): value for leaf, value in changed.items()})
            candidates.append(Candidate(path, None if inherited else original, content, boundary))
            staged_profiles[name] = content
            overrides = config.model_presets.get(name, {})
            for leaf, value in changed.items():
                override = overrides.get(leaf[0])
                if override is None:
                    continue
                override_values = {
                    ("coordinator_model",): override.coordinator_model,
                    ("coordinator_effort",): override.coordinator_effort,
                    **{("models", key): val for key, val in override.models.items()},
                    **{("effort", key): val for key, val in override.effort.items()},
                }
                if override_values.get(leaf[1:]) is not None:
                    team_changes[("model_presets", name, *leaf)] = value
        team_content = upsert_strings(scoped_text, team_changes)
        if team_content != scoped_text:
            candidates.append(Candidate(config_path, scoped_text, team_content, boundary))

        def validate_candidates() -> None:
            candidate_layers = [*layers[:-1], (scope, boundary, _parse(team_content, config_path))]
            candidate_config = _layered_config(boundary, candidate_layers)
            with tempfile.TemporaryDirectory(prefix="agent-team-config-") as shadow:
                references = dict(candidate_config.target_profiles)
                roots = dict(candidate_config.target_profile_roots)
                for name, content in staged_profiles.items():
                    shadow_path = Path(shadow) / f"{name}.toml"
                    shadow_path.write_text(content, encoding="utf-8")
                    references[name] = shadow_path.name
                    roots[name] = Path(shadow)
                candidate_config = replace(candidate_config, target_profiles=references, target_profile_roots=roots)
                for name in dict.fromkeys((*candidate_config.enabled_targets, *candidate_config.model_presets)):
                    effective = resolve_target_profile(candidate_config, name, boundary)
                    for key, desired in selected.get(name, {}).items():
                        if effective.presets[key] != desired:
                            raise _fail(name, "candidate configuration does not preserve selected routing")

        validate_candidates()
        if not candidates:
            emit("No model preset changes.")
            return 0
        for candidate in candidates:
            emit("".join(difflib.unified_diff(
                (candidate.original or "").splitlines(keepends=True), candidate.content.splitlines(keepends=True),
                fromfile=str(candidate.path), tofile=str(candidate.path),
            )))
        if dry_run:
            emit("Dry run: no files saved.")
            return 0
        if read("Save these changes? [yes/No]: ").strip().lower() != "yes":
            emit("Cancelled: no files saved (enter 'yes' to save).")
            return 0
        validate_candidates()
        apply_candidates(tuple(candidates), snapshots)
        emit(f"Saved model presets. Reinstall with: agent-team install --scope {scope} --target {','.join(targets)} --apply")
        return 0
    except (EOFError, KeyboardInterrupt):
        emit("Cancelled: no files saved.")
        return 0


def edit_model_presets(
    root: Path, *, scope: str = "project", target: str | None = None,
    preset: str | None = None, dry_run: bool = False,
    read: Callable[[str], str] | None = None, emit: Callable[[str], None] = print,
) -> int:
    """Edit selected presets, treating interruption during discovery as cancellation."""
    try:
        return _edit_model_presets(root, scope=scope, target=target, preset=preset,
                                   dry_run=dry_run, read=read, emit=emit)
    except (EOFError, KeyboardInterrupt):
        emit("Cancelled: no files saved.")
        return 0
    except OSError as exc:
        raise _fail("config model-presets", f"configuration I/O failed: {exc}") from exc


def _role_source_snapshot(
    config: TeamConfig, root: Path, snapshots: dict[Path, str] | None = None,
) -> tuple[tuple[str, ...], ...]:
    """Capture inventory, resolved paths and bytes for every participating definition."""
    inventory: list[tuple[str, ...]] = []
    sources = config.scoped_role_sources or tuple((root, source) for source in config.role_sources)
    for scope_root, source in sources:
        if source == "builtin:roles":
            base = resources.files("agent_team.assets").joinpath("definitions", "roles")
            for role_id in ROLE_IDS:
                directory = base.joinpath(role_id)
                inventory.append((source, role_id, directory.joinpath("role.toml").read_bytes().decode("utf-8"),
                                  directory.joinpath("instructions.md").read_bytes().decode("utf-8")))
            continue
        directory = scope_root / source
        resolved = directory.resolve()
        boundary = scope_root.resolve()
        if resolved != boundary and boundary not in resolved.parents:
            raise _fail(directory, "role source escapes its defining scope", "path")
        if not directory.is_dir():
            raise _fail(directory, "role source directory does not exist", "missing")
        inventory.append((str(scope_root), source, str(resolved)))
        for path in sorted(directory.glob("*/role.toml")):
            instructions = path.with_name("instructions.md")
            for dependency in (path, instructions):
                if boundary not in dependency.resolve().parents:
                    raise _fail(dependency, "role source escapes its defining scope", "path")
            role_content, instruction_content = _read(path), _read(instructions)
            if snapshots is not None:
                snapshots[path] = role_content
                snapshots[instructions] = instruction_content
            inventory.append((str(path), str(path.resolve()), role_content,
                              str(instructions.resolve()), instruction_content))
    return tuple(inventory)


def _role_choice(
    label: str, options: tuple[str, ...], current: str, keep_preset: bool,
    read: Callable[[str], str], emit: Callable[[str], None],
) -> str | None:
    """Return only explicitly selected leaves, retaining empty-input presence semantics."""
    keep = "keep coordinator preset"
    answers: list[str] = []
    def capture(prompt: str) -> str:
        answer = read(prompt)
        answers.append(answer.strip())
        return answer
    chosen = _menu(label, (keep, *options) if keep_preset else options,
                   keep if keep_preset else current, capture, emit)
    return chosen if answers[-1] and chosen != keep else None


def _edit_roles(
    root: Path, *, scope: str, role: str | None, target: str | None, dry_run: bool,
    read: Callable[[str], str], emit: Callable[[str], None],
) -> int:
    if scope not in ("project", "user") or (role is not None and role not in ROLE_IDS):
        raise _fail("selection", "invalid scope or builtin role")
    root = root.resolve()
    user_root = user_config_root()
    if scope == "user" and user_root.is_symlink():
        raise _fail(user_root, "symlink destinations are unsupported", "path")
    user_root = user_root.resolve()
    boundary = root if scope == "project" else user_root
    config_path = boundary / ".agent-team" / "team.toml" if scope == "project" else boundary / "team.toml"
    if scope == "project":
        require_project_context(root)
    _safe_destination(config_path, boundary)
    scoped_text = _read(config_path)
    scoped_data = _parse(scoped_text, config_path)
    snapshots = {config_path: scoped_text}
    layers = []
    inherited_path = user_root / "team.toml"
    inherits = scope == "project" and scoped_data.get("inherit_user_defaults", True)
    inherited_present = inherits and inherited_path.exists()
    if inherited_present:
        snapshots[inherited_path] = _read(inherited_path)
        layers.append(("user", user_root, _parse(snapshots[inherited_path], inherited_path)))
    layers.append((scope, boundary, scoped_data))
    config = _layered_config(boundary, layers)
    source_snapshot = _role_source_snapshot(config, boundary, snapshots)
    targets = tuple(item.strip() for item in target.split(",")) if target is not None else config.enabled_targets
    if not targets:
        raise _fail("targets", "no enabled targets; select a configured target explicitly")
    if len(set(targets)) != len(targets):
        raise _fail("targets", "target names must be unique")
    for name in targets:
        if name not in TARGETS or name not in config.target_profiles:
            raise _fail("targets", f"target {name!r} must be known and have a configured profile")
    profile_paths: dict[Path, Path] = {}
    for name, reference in config.target_profiles.items():
        if not reference.startswith("builtin:"):
            path = config.target_profile_roots[name] / reference
            snapshots[path] = _read(path)
            profile_paths[path] = path.resolve()
    definitions = {
        name: {item.role_id: item for item in load_roles(config, boundary, target=name)}
        for name in targets
    }

    def check_sources() -> None:
        for path, original in snapshots.items():
            if _read(path) != original:
                raise _fail(path, "configuration changed since preview; rerun the command", "conflict")
        for path, resolved in profile_paths.items():
            if path.resolve() != resolved:
                raise _fail(path, "profile source resolution changed; rerun the command", "conflict")
        if inherits and inherited_path.exists() != inherited_present:
            raise _fail(inherited_path, "inherited configuration discovery changed; rerun the command", "conflict")
        if _role_source_snapshot(config, boundary) != source_snapshot:
            raise _fail("role_sources", "role source contents, paths or inventory changed; rerun the command", "conflict")

    check_sources()
    changes: dict[tuple[str, ...], str] = {}
    for name in targets:
        for role_id in (role,) if role else ROLE_IDS:
            definition = definitions[name][role_id]
            emit(f"{name} / {role_id}: definition source {definition.source}")
            for field, options, current in (
                ("model_class", _CLASSES, definition.model_class),
                ("effort", _EFFORTS, definition.effort),
            ):
                origin = definition.routing_override_origins.get(field)
                dedicated = role_id == "coordinator" and origin is None
                display = "dedicated coordinator preset" if dedicated else current
                bound = config.target_role_overrides.get(name, {}).get(role_id)
                binding = "target-bound" if bound is not None and getattr(bound, field) is not None else "global"
                source = f"{origin} {binding} routing overlay" if origin else f"definition {definition.source}"
                emit(f"  {field}: {display} (semantic value {current}; source {source})")
                choice = _role_choice(f"{name} / {role_id} / {field}", options, current, dedicated, read, emit)
                if choice is not None:
                    changes[("roles", role_id, "targets", name, field)] = choice
    content = upsert_strings(scoped_text, changes)

    def validate_candidate() -> None:
        candidate_layers = [*layers[:-1], (scope, boundary, _parse(content, config_path))]
        candidate = _layered_config(boundary, candidate_layers)
        load_roles(candidate, boundary)
        for name in candidate.target_profiles:
            roles = {item.role_id: item for item in load_roles(candidate, boundary, target=name)}
            resolve_target_profile(candidate, name, boundary)
            for (_, role_id, _, selected_target, field), expected in changes.items():
                if selected_target != name:
                    continue
                pin = candidate.target_role_overrides.get(name, {}).get(role_id)
                if (pin is None or getattr(pin, field) != expected
                        or getattr(roles[role_id], field) != expected
                        or roles[role_id].routing_override_origins.get(field) != scope):
                    raise _fail(role_id, "candidate does not preserve explicitly selected scoped routing")

    check_sources()
    validate_candidate()
    if content == scoped_text:
        emit("No role routing changes.")
        return 0
    emit("".join(difflib.unified_diff(
        scoped_text.splitlines(keepends=True), content.splitlines(keepends=True),
        fromfile=str(config_path), tofile=str(config_path),
    )))
    if dry_run:
        emit("Dry run: no files saved.")
        return 0
    if read("Save these changes? [yes/No]: ").strip().lower() != "yes":
        emit("Cancelled: no files saved (enter 'yes' to save).")
        return 0
    check_sources()
    validate_candidate()
    check_sources()
    apply_candidates((Candidate(config_path, scoped_text, content, boundary),), snapshots)
    affected = tuple(name for name in targets if name in config.enabled_targets and any(leaf[3] == name for leaf in changes))
    if affected:
        emit(f"Saved role routing. Reinstall with: agent-team install --scope {scope} --target {','.join(affected)} --apply")
    else:
        emit("Saved role routing.")
    return 0


def edit_roles(
    root: Path, *, scope: str = "project", role: str | None = None, target: str | None = None, dry_run: bool = False,
    read: Callable[[str], str] | None = None, emit: Callable[[str], None] = print,
) -> int:
    """Interactively pin semantic routing leaves without discovering native clients."""
    try:
        return _edit_roles(root, scope=scope, role=role, target=target, dry_run=dry_run, read=read or input, emit=emit)
    except (EOFError, KeyboardInterrupt):
        emit("Cancelled: no files saved.")
        return 0
    except OSError as exc:
        raise _fail("config roles", f"configuration I/O failed: {exc}") from exc
