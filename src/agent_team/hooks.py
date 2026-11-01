from __future__ import annotations

import copy
import difflib
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from agent_team.config import load_team_config
from agent_team.fs import atomic_write
from agent_team.recovery import discover_runs, recovery_status, render_context, select_run
from agent_team.run_state import bind, fail
from agent_team.runs import utc_now


def invocation_prefix() -> str:
    """Prefer the running interpreter so hooks cannot pick up a stale install."""
    package_root = Path(__file__).resolve().parent.parent
    return f"PYTHONPATH={shlex.quote(str(package_root))} {shlex.quote(sys.executable)} -m agent_team"


def hook_groups(fail_closed: bool = False) -> dict[str, list[dict[str, Any]]]:
    prefix = invocation_prefix()
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


def manage_hooks(root: Path, *, remove: bool = False, apply: bool = False,
                 fail_closed: bool = False, hooks_file: str = ".claude/settings.local.json") -> str:
    root = root.resolve()
    path = root / hooks_file
    state_path = root / ".agent-team" / "hooks-state.json"
    for target in (path, state_path):
        if target.is_symlink() or not target.resolve().is_relative_to(root) or target.resolve() == root:
            fail("hook files must remain inside the project")
    if path.resolve() == state_path.resolve() or not path.name.endswith(".json"):
        fail("invalid hooks file")
    before = path.read_text(encoding="utf-8") if path.exists() else None
    original = _read_json(path)
    state = _read_json(state_path)
    if state and state.get("path") != path.relative_to(root).as_posix():
        fail("another hooks file is managed; remove it before changing target")
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
    generated = {} if remove else hook_groups(fail_closed)
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
        atomic_write(state_path, json.dumps({"path": path.relative_to(root).as_posix(),
                     "groups": generated, "updated_at": utc_now()}, indent=2) + "\n")
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


def run_hook(action: str, fail_closed: bool = False) -> int:
    try:
        payload = json.loads(sys.stdin.read(1024 * 1024))
        if not isinstance(payload, dict):
            fail("hook input must be an object")
        expected = "PreCompact" if action == "precompact" else "SessionStart"
        if payload.get("hook_event_name") != expected:
            fail("hook event mismatch")
        session = payload.get("session_id")
        cwd = payload.get("cwd")
        if not isinstance(session, str) or not session or not isinstance(cwd, str):
            fail("hook requires session_id and cwd")
        root = Path.cwd().resolve()
        if not Path(cwd).resolve().is_relative_to(root):
            fail("hook cwd does not belong to invocation project")
        config = load_team_config(root)
        candidates = discover_runs(root, config)
        candidate, notices = select_run(candidates, root, session_id=session)
        if candidate is None:
            fail("no unambiguous active run; use agent-team resume status and bind --slug")
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
    except Exception as exc:
        if action == "precompact":
            print(f"agent-team PreCompact: {exc}", file=sys.stderr)
            return 2 if fail_closed else 1
        context = f"agent-team 恢复失败，暂停写操作：{exc}。运行 agent-team resume status --json 核对候选及绑定。"[:9000]
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                           "additionalContext": context}}, ensure_ascii=False))
    return 0
