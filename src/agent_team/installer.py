from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from agent_team.diagnostics import Diagnostic, ValidationFailure
from agent_team.fs import atomic_write


@dataclass(frozen=True)
class InstallAction:
    path: str
    action: str
    reason: str


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _state_path(target_root: Path) -> Path:
    return target_root / ".agent-team" / "install-state.json"


def _load_state(target_root: Path) -> dict[str, Any]:
    path = _state_path(target_root)
    if not path.exists():
        return {"schema_version": 1, "files": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationFailure([Diagnostic(str(path), str(exc), code="state")])
    if state.get("schema_version") != 1 or not isinstance(state.get("files"), dict):
        raise ValidationFailure([Diagnostic(str(path), "unsupported install state", code="state")])
    for relative, record in state["files"].items():
        if (
            not isinstance(relative, str)
            or not isinstance(record, dict)
            or not isinstance(record.get("sha256"), str)
        ):
            raise ValidationFailure([Diagnostic(str(path), "contains an invalid file record", code="state")])
    return state


def _classify(
    target_root: Path,
    files: dict[PurePosixPath, str],
    state: dict[str, Any],
) -> list[InstallAction]:
    actions: list[InstallAction] = []
    records = state["files"]
    for relative, content in files.items():
        key = relative.as_posix()
        destination = target_root / Path(relative)
        desired_hash = _digest(content.encode("utf-8"))
        record = records.get(key)
        if not destination.exists():
            actions.append(InstallAction(key, "create", "destination is absent"))
            continue
        if not destination.is_file():
            actions.append(InstallAction(key, "directory", "destination is not a regular file"))
            continue
        current_hash = _digest(destination.read_bytes())
        if record is None:
            if current_hash == desired_hash:
                actions.append(InstallAction(key, "adopt", "unmanaged file already has desired content"))
            else:
                actions.append(InstallAction(key, "conflict", "existing file is unmanaged"))
            continue
        if current_hash != record.get("sha256"):
            actions.append(InstallAction(key, "drift", "managed file changed since installation"))
        elif current_hash == desired_hash:
            actions.append(InstallAction(key, "unchanged", "managed content is current"))
        else:
            actions.append(InstallAction(key, "update", "managed source changed"))
    return actions


def install_files(
    *, target: str, target_root: Path, files: dict[PurePosixPath, str], apply: bool,
    force: bool, backups: bool,
) -> list[InstallAction]:
    target_root = target_root.resolve()
    state = _load_state(target_root)
    actions = _classify(target_root, files, state)
    invalid = [action for action in actions if action.action == "directory"]
    if invalid:
        raise ValidationFailure([
            Diagnostic(action.path, action.reason, code=action.action) for action in invalid
        ])
    conflicts = [action for action in actions if action.action in {"conflict", "drift"}]
    if conflicts and not force:
        raise ValidationFailure([
            Diagnostic(action.path, f"{action.reason}; rerun with --force to back up and replace", code=action.action)
            for action in conflicts
        ])
    if conflicts and force and not backups:
        raise ValidationFailure([
            Diagnostic(action.path, "forced replacement requires backups", code="backup")
            for action in conflicts
        ])
    if not apply:
        return actions

    timestamp = _timestamp()
    backup_stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    for action in actions:
        relative = PurePosixPath(action.path)
        destination = (target_root / Path(relative)).resolve()
        if destination != target_root and target_root not in destination.parents:
            raise ValidationFailure([Diagnostic(action.path, "install path escapes target root", code="path")])
        content = files[relative]
        backup_reference: str | None = None
        if action.action in {"conflict", "drift"}:
            backup = target_root / ".agent-team" / "backups" / backup_stamp / Path(relative)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, backup)
            backup_reference = str(backup.relative_to(target_root))
        if action.action not in {"unchanged", "adopt"}:
            atomic_write(destination, content)
        state["files"][relative.as_posix()] = {
            "target": target,
            "sha256": _digest(content.encode("utf-8")),
            "installed_at": timestamp,
            "backup": backup_reference,
        }
    atomic_write(_state_path(target_root), json.dumps(state, indent=2, sort_keys=True) + "\n")
    return actions


def actions_json(actions: list[InstallAction]) -> str:
    return json.dumps([asdict(action) for action in actions], indent=2, sort_keys=True)
