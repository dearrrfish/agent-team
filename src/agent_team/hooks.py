from __future__ import annotations

import copy
import difflib
import json
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_team.config import load_team_config
from agent_team.fs import atomic_write
from agent_team.recovery import (
    discover_runs,
    recovery_status,
    render_context,
    select_run,
)
from agent_team.run_state import bind, fail
from agent_team.runs import utc_now


def invocation_prefix(invocation: str = "auto", command_prefix: str | None = None) -> str:
    """Resolve hook command prefix, avoiding ephemeral nix store hashes when possible."""
    if command_prefix is not None and command_prefix.strip():
        return command_prefix.strip()
    if invocation == "cli":
        return "agent-team"
    if invocation == "interpreter":
        package_root = Path(__file__).resolve().parent.parent
        return f"PYTHONPATH={shlex.quote(str(package_root))} {shlex.quote(sys.executable)} -m agent_team"
    if invocation == "auto":
        which_cli = shutil.which("agent-team")
        if which_cli:
            return "agent-team"
        if sys.executable.startswith("/nix/store/"):
            print("agent-team: warning: installing hooks with a nix store interpreter path that "
                  "may become invalid after a system update or nix gc; consider installing agent-team "
                  "to your profile/PATH or specifying --command-prefix", file=sys.stderr)
        package_root = Path(__file__).resolve().parent.parent
        return f"PYTHONPATH={shlex.quote(str(package_root))} {shlex.quote(sys.executable)} -m agent_team"
    fail(f"unsupported invocation strategy: {invocation}")


def hook_groups(fail_closed: bool = False, invocation: str = "auto",
                command_prefix: str | None = None,
                target: str = "claude", scope: str = "project") -> dict[str, Any]:
    if scope not in {"project", "user"}:
        fail(f"unsupported hook scope: {scope}")
    if scope == "user" and target != "antigravity":
        fail("user-scope hooks are only supported for --target antigravity")
    prefix = invocation_prefix(invocation=invocation, command_prefix=command_prefix)
    if target == "codex":
        return {
            "PreCompact": [{"matcher": "manual|auto", "hooks": [{
                "type": "command",
                "command": f"{prefix} resume hook precompact" + (" --fail-closed" if fail_closed else ""),
                "timeout": 30, "onFailure": "block" if fail_closed else "continue"}]}],
            "SessionStart": [{"matcher": "compact", "hooks": [{
                "type": "command", "command": f"{prefix} resume hook session-start",
                "timeout": 30, "additionalContextLimit": 0}]}],
        }
    if target == "antigravity":
        # Antigravity keys hooks by a namespace and has no PreCompact event; only
        # SessionStart can inject recovery context. User-scope hooks run from the
        # global config directory, so they use a dedicated action that resolves
        # the workspace from the payload instead of the hook cwd.
        action = ("antigravity-global-session-start" if scope == "user"
                  else "antigravity-session-start")
        return {"agent-team": {"SessionStart": [{
            "type": "command",
            "command": f"{prefix} resume hook {action}",
            "timeout": 30,
        }]}}
    return {event: [{"matcher": matcher, "hooks": [{"type": "command",
            "command": f"{prefix} resume hook {action}" + (
                " --fail-closed" if action == "precompact" and fail_closed else ""),
            "timeout": 30, "onFailure": "block" if action == "precompact" and fail_closed else "continue"}]}]
            for event, matcher, action in (("PreCompact", "manual|auto", "precompact"),
                                           ("SessionStart", "compact", "session-start"))}


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"expected JSON object: {path}")
    return value


def _write_hooks(root: Path, path: Path, state_path: Path, before: str | None,
                 after: str, state_record: dict[str, Any], apply: bool) -> str:
    diff = "".join(difflib.unified_diff((before or "").splitlines(True), after.splitlines(True),
                                     fromfile=str(path), tofile=str(path)))
    if not apply:
        return diff
    backup = root / ".agent-team" / "backups" / ("hooks-" + utc_now().replace(":", "-") + ".json")
    if not backup.resolve().is_relative_to(root):
        fail("backup path escapes project")
    if before is not None:
        atomic_write(backup, before)
    old_state = state_path.read_text(encoding="utf-8") if state_path.exists() else None
    if (path.read_text(encoding="utf-8") if path.exists() else None) != before:
        fail("settings changed during preview; retry")
    try:
        atomic_write(path, after)
        atomic_write(state_path, json.dumps(state_record, indent=2) + "\n")
    except OSError:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, before)
        if old_state is None:
            state_path.unlink(missing_ok=True)
        else:
            atomic_write(state_path, old_state)
        raise
    return diff


def _manage_antigravity_hooks(base: Path, path: Path, state_path: Path, before: str | None,
                              original: dict, state: dict, *, remove: bool, apply: bool,
                              fail_closed: bool, invocation: str,
                              command_prefix: str | None, scope: str) -> str:
    updated = copy.deepcopy(original)
    namespace = "agent-team"
    owned = state.get("namespace")
    owned_block = state.get("block")
    if owned:
        if owned != namespace:
            fail("another hook namespace is managed; remove it before changing target")
        if owned in updated:
            if updated[owned] != owned_block:
                fail("managed hook namespace changed; reconcile manually before updating")
            del updated[owned]
    if not remove:
        generated = hook_groups(fail_closed, invocation=invocation,
                                command_prefix=command_prefix, target="antigravity",
                                scope=scope)
        block = generated[namespace]
        if namespace in updated and updated[namespace] != block:
            fail("identical hook namespace exists with different content; reconcile manually")
        updated[namespace] = block
    after = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    if updated == original:
        return "No hook changes."
    state_record: dict[str, Any] = {
        "path": path.relative_to(base).as_posix(),
        "namespace": namespace,
        "block": None if remove else updated.get(namespace),
        "updated_at": utc_now(),
        "invocation": invocation,
        "target": "antigravity",
        "scope": scope,
    }
    if command_prefix:
        state_record["command_prefix"] = command_prefix
    return _write_hooks(base, path, state_path, before, after, state_record, apply)


def manage_hooks(root: Path, *, remove: bool = False, apply: bool = False,
                 fail_closed: bool = False, hooks_file: str | None = None,
                 invocation: str = "auto", command_prefix: str | None = None,
                 target: str = "claude", scope: str = "project") -> str:
    if target not in {"claude", "codex", "antigravity"}:
        fail(f"unsupported hook target: {target}")
    if scope not in {"project", "user"}:
        fail(f"unsupported hook scope: {scope}")
    if scope == "user" and target != "antigravity":
        fail("user-scope hooks are only supported for --target antigravity")
    root = root.resolve()
    if scope == "user":
        # Antigravity discovers user-scope hooks in ~/.gemini/config/hooks.json.
        # Keep ownership state and backups in the user agent-team directory.
        base = Path.home().resolve()
        default_file = ".gemini/config/hooks.json"
        state_file: str | None = ".agent-team/hooks-state-antigravity-user.json"
        location = "the user home directory"
    else:
        base = root
        default_file = {
            "codex": ".codex/hooks.json",
            "antigravity": ".agents/hooks.json",
        }.get(target, ".claude/settings.local.json")
        state_file = None
        location = "the project"
    hooks_file = hooks_file or default_file
    path = base / hooks_file
    if state_file is not None:
        state_path = base / state_file
    elif target == "codex":
        state_path = base / ".agent-team" / "hooks-state-codex.json"
    elif target == "antigravity":
        state_path = base / ".agent-team" / "hooks-state-antigravity.json"
    else:
        claude_state = base / ".agent-team" / "hooks-state-claude.json"
        legacy_state = base / ".agent-team" / "hooks-state.json"
        state_path = claude_state if claude_state.exists() or not legacy_state.exists() else legacy_state
    for target_path in (path, state_path):
        if target_path.is_symlink() or not target_path.resolve().is_relative_to(base) or target_path.resolve() == base:
            fail(f"hook files must remain inside {location}")
    if path.resolve() == state_path.resolve() or not path.name.endswith(".json"):
        fail("invalid hooks file")
    before = path.read_text(encoding="utf-8") if path.exists() else None
    original = _read_json(path)
    state = _read_json(state_path)
    if state and state.get("path") != path.relative_to(base).as_posix():
        fail("another hooks file is managed; remove it before changing target")
    if target == "antigravity":
        return _manage_antigravity_hooks(
            base, path, state_path, before, original, state, remove=remove, apply=apply,
            fail_closed=fail_closed, invocation=invocation, command_prefix=command_prefix,
            scope=scope)
    updated = copy.deepcopy(original)
    hooks = updated.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        fail("settings hooks must be an object")
    owned = state.get("groups", {})
    if not isinstance(owned, dict):
        fail("invalid hooks ownership state")
    for event, groups in owned.items():
        existing = hooks.get(event, [])
        if not isinstance(existing, list) or not isinstance(groups, list):
            fail("invalid hook event array")
        for group in groups:
            if existing.count(group) != 1:
                fail("managed hook changed or duplicated; reconcile manually before updating")
            existing.remove(group)
        if not existing:
            hooks.pop(event, None)
    generated = {} if remove else hook_groups(fail_closed, invocation=invocation,
                                              command_prefix=command_prefix, target=target)
    for event, groups in generated.items():
        existing = hooks.setdefault(event, [])
        if not isinstance(existing, list):
            fail("hook event must be an array")
        for group in groups:
            if group in existing:
                fail("identical unmanaged hook exists; refusing to claim ownership")
            existing.append(group)
    if not hooks:
        updated.pop("hooks", None)
    after = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    if updated == original:
        return "No hook changes."
    state_record: dict[str, Any] = {
        "path": path.relative_to(root).as_posix(),
        "groups": generated,
        "updated_at": utc_now(),
        "invocation": invocation,
        "target": target,
    }
    if command_prefix:
        state_record["command_prefix"] = command_prefix
    return _write_hooks(root, path, state_path, before, after, state_record, apply)


_PROJECT_HOOK_STATES = {
    "hooks-state.json": ("claude", "project", True),
    "hooks-state-claude.json": ("claude", "project", False),
    "hooks-state-codex.json": ("codex", "project", False),
    "hooks-state-antigravity.json": ("antigravity", "project", False),
}
_USER_HOOK_STATES = {
    "hooks-state-antigravity-user.json": ("antigravity", "user", False),
}


@dataclass
class HookState:
    state_path: Path
    base: Path
    target: str
    scope: str
    legacy: bool
    status: str
    record: dict[str, Any] | None = None
    hooks_path: Path | None = None
    detail: str = ""


def _state_match(record: dict[str, Any], target: str, hooks: dict) -> str:
    """Classify a recorded ownership block as managed, missing, or modified."""
    if target == "antigravity":
        namespace = record.get("namespace")
        block = record.get("block")
        if not isinstance(namespace, str) or block is None or namespace not in hooks:
            return "missing"
        return "managed" if hooks[namespace] == block else "modified"
    groups = record.get("groups")
    event_hooks = hooks.get("hooks")
    if not isinstance(groups, dict) or not groups or not isinstance(event_hooks, dict):
        return "missing"
    expected = 0
    seen = 0
    for event, recorded in groups.items():
        existing = event_hooks.get(event, [])
        if not isinstance(recorded, list) or not isinstance(existing, list):
            return "modified"
        expected += len(recorded)
        for group in recorded:
            if existing.count(group) == 1:
                seen += 1
            elif group in existing:
                return "modified"
    if expected == 0:
        return "missing"
    return "managed" if seen == expected else "missing"


def inspect_hook_states(root: Path) -> list[HookState]:
    """Read every known ownership record without modifying any file."""
    root = root.resolve()
    home = Path.home().resolve()
    candidates = [(root / ".agent-team" / name, root, *value)
                  for name, value in _PROJECT_HOOK_STATES.items()]
    candidates += [(home / ".agent-team" / name, home, *value)
                   for name, value in _USER_HOOK_STATES.items()]
    claude_state_exists = (root / ".agent-team" / "hooks-state-claude.json").exists()
    states: list[HookState] = []
    for state_path, base, target, scope, legacy in candidates:
        if not state_path.exists() and not state_path.is_symlink():
            continue
        state = HookState(state_path, base, target, scope, legacy, "invalid")
        try:
            if state_path.is_symlink() or not state_path.resolve().is_relative_to(base):
                state.status, state.detail = "error", "state file escapes its base directory"
                states.append(state)
                continue
            record = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                state.status, state.detail = "invalid", "missing hooks path"
                states.append(state)
                continue
            state.record = record
            if isinstance(record.get("target"), str):
                state.target = record["target"]
            if isinstance(record.get("scope"), str):
                state.scope = record["scope"]
            hooks_path = base / record["path"]
            if not hooks_path.resolve().is_relative_to(base):
                state.status, state.detail = "error", "hooks path escapes its base directory"
                states.append(state)
                continue
            state.hooks_path = hooks_path
            if legacy and claude_state_exists:
                state.status, state.detail = "superseded", "hooks-state-claude.json exists"
                states.append(state)
                continue
            if not hooks_path.exists():
                state.status, state.detail = "stale", "hooks file is missing"
                states.append(state)
                continue
            hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
            if not isinstance(hooks, dict):
                state.status, state.detail = "invalid", "hooks file is not a JSON object"
                states.append(state)
                continue
            match = _state_match(record, state.target, hooks)
            if match == "managed":
                state.status = "legacy" if legacy else "managed"
            elif match == "modified":
                state.status, state.detail = "modified", "managed hooks changed; reconcile manually"
            else:
                state.status, state.detail = "stale", "managed hooks are no longer present"
        except (OSError, ValueError) as exc:
            state.status, state.detail = "invalid", str(exc)
        states.append(state)
    return states


def hook_state_report(root: Path, *, apply: bool = False) -> str:
    """Report, migrate, or clean hook ownership records; never edits client hooks."""
    states = inspect_hook_states(root)
    if not states:
        return "No hook state files."
    lines: list[str] = []
    changed = 0
    for state in states:
        shown = state.state_path
        if state.status == "managed":
            lines.append(f"ok {shown} ({state.target}, {state.scope})")
        elif state.status == "legacy":
            destination = state.base / ".agent-team" / "hooks-state-claude.json"
            lines.append(f"migrate {shown} -> {destination}")
            if apply and state.record is not None:
                record = dict(state.record, target="claude", scope="project")
                atomic_write(destination, json.dumps(record, indent=2) + "\n")
                state.state_path.unlink()
                changed += 1
        elif state.status in {"stale", "superseded"}:
            lines.append(f"remove {shown}: {state.detail}")
            if apply:
                state.state_path.unlink()
                changed += 1
        elif state.status == "modified":
            lines.append(f"manual {shown}: {state.detail}")
        else:
            lines.append(f"error {shown}: {state.detail}")
    if not apply and any(state.status in {"legacy", "stale", "superseded"} for state in states):
        lines.append("Preview only; use --reconcile --apply to migrate or remove these states.")
    elif apply:
        lines.append("No state changes." if changed == 0 else f"Updated {changed} state file(s).")
    return "\n".join(lines)


def hook_state_payload(root: Path) -> dict[str, Any]:
    """Machine-readable form of inspect_hook_states for --status --json."""
    return {"states": [{
        "state_path": str(state.state_path),
        "hooks_path": None if state.hooks_path is None else str(state.hooks_path),
        "target": state.target,
        "scope": state.scope,
        "status": state.status,
        "legacy": state.legacy,
        "detail": state.detail,
    } for state in inspect_hook_states(root)]}


def run_hook(action: str, fail_closed: bool = False) -> int:
    global_antigravity = action == "antigravity-global-session-start"
    antigravity = action == "antigravity-session-start" or global_antigravity
    try:
        payload = json.loads(sys.stdin.read(1024 * 1024))
        if not isinstance(payload, dict):
            fail("hook input must be an object")
        if antigravity:
            session = payload.get("conversationId") or payload.get("conversation_id") or payload.get(
                "session_id") or payload.get("sessionId")
            workspace_paths = payload.get("workspacePaths") or payload.get("workspace_paths")
            cwd = (workspace_paths[0] if isinstance(workspace_paths, list) and workspace_paths
                   else payload.get("cwd"))
        else:
            expected = "PreCompact" if action == "precompact" else "SessionStart"
            event_name = payload.get("hook_event_name") or payload.get("hookEventName")
            if event_name != expected:
                fail("hook event mismatch")
            session = payload.get("session_id") or payload.get("sessionId") or payload.get(
                "thread_id") or payload.get("threadId")
            cwd = payload.get("cwd")
        if not isinstance(session, str) or not session or not isinstance(cwd, str):
            fail("hook requires a session id and cwd")
        root = Path.cwd().resolve()
        if antigravity:
            # Antigravity runs project hooks from <project>/.agents and user-scope
            # hooks from ~/.gemini/config, so the workspace path from the payload
            # is authoritative. Project hooks must still be launched from inside
            # the workspace they claim.
            workspace_root = Path(cwd).resolve()
            if not workspace_root.is_dir():
                fail("hook workspace does not exist")
            if not global_antigravity and not root.is_relative_to(workspace_root):
                fail("hook cwd does not belong to invocation project")
            root = workspace_root
        elif not Path(cwd).resolve().is_relative_to(root):
            fail("hook cwd does not belong to invocation project")
        if global_antigravity and not (root / ".agent-team").is_dir():
            # User-scope hooks run in every workspace; stay silent where
            # agent-team is not used at all.
            return 0
        config = load_team_config(root)
        candidates = discover_runs(root, config)
        if global_antigravity and not candidates:
            return 0
        candidate, notices = select_run(candidates, root, session_id=session, session_only=True)
        if candidate is None:
            if notices:
                fail("invalid session binding: " + "; ".join(notices))
            # Unbound sessions are not managed by agent-team; stay silent.
            return 0
        status = recovery_status(candidate, root, config)
        if action == "precompact":
            snapshot = candidate.path.parent / "recovery" / "snapshot.json"
            if not snapshot.resolve().is_relative_to(candidate.path.parent.resolve()):
                fail("snapshot escapes run")
            atomic_write(snapshot, json.dumps({"at": utc_now(), "status": status}, ensure_ascii=False) + "\n")
            bind(root, config, candidate.slug, session)
            return 0
        context = render_context(status)
        if notices:
            context = ("恢复指针存在诊断，请核对 resume status --json。\n" + context)[:9000]
    # Hook failures must never break the client session; every error becomes a
    # documented exit code or an injected warning.
    except Exception as exc:  # noqa: BLE001
        if action == "precompact":
            print(f"agent-team PreCompact: {exc}", file=sys.stderr)
            return 2 if fail_closed else 1
        context = f"agent-team 恢复失败，暂停写操作：{exc}。运行 agent-team resume status --json 核对候选及绑定。"[:9000]
    if antigravity:
        print(json.dumps({"injectSteps": [{"systemMessage": {"systemMessage": context}}]},
                         ensure_ascii=False))
        return 0
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                           "additionalContext": context}}, ensure_ascii=False))
    return 0
