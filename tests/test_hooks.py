import json
import os
import subprocess
import unittest

from agent_team.hooks import hook_groups, manage_hooks
from tests import test_recovery


class HookTests(unittest.TestCase):
    setUp = test_recovery.RecoveryTests.setUp
    create_run = test_recovery.RecoveryTests.create_run

    def test_preview_install_idempotence_and_remove_preserves_existing(self):
        target = self.root / ".claude" / "settings.local.json"
        target.parent.mkdir()
        existing = {"env": {"KEEP": "yes"}, "hooks": {"SessionStart": [{
            "matcher": "compact", "hooks": [{"type": "command", "command": "AskHuman --show-last"}]}]}}
        target.write_text(json.dumps(existing))
        before = target.read_bytes()
        manage_hooks(self.root)
        self.assertEqual(before, target.read_bytes())
        self.assertFalse((self.root / ".agent-team" / "hooks-state.json").exists())
        manage_hooks(self.root, apply=True)
        installed = json.loads(target.read_text())
        self.assertEqual(installed["hooks"]["SessionStart"][0], existing["hooks"]["SessionStart"][0])
        self.assertEqual(manage_hooks(self.root, apply=True), "No hook changes.")
        manage_hooks(self.root, remove=True, apply=True)
        self.assertEqual(json.loads(target.read_text()), existing)

    def test_generated_commands_receive_real_stdin(self):
        self.create_run()
        groups = hook_groups()
        payload = {"session_id": "private-session", "cwd": str(self.root), "hook_event_name": "PreCompact"}
        environment = os.environ.copy()
        environment["HOME"] = str(self.root / "isolated-home")
        for event in ("PreCompact", "SessionStart"):
            payload["hook_event_name"] = event
            command = groups[event][0]["hooks"][0]["command"]
            result = subprocess.run(command, shell=True, cwd=self.root, env=environment,
                                    input=json.dumps(payload), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            if event == "SessionStart":
                context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
                self.assertIn("first", context)
                self.assertLessEqual(len(context), 9000)
        sessions = self.root / ".agent-team" / "sessions"
        self.assertEqual(len(list(sessions.glob("*.json"))), 1)
        self.assertNotIn("private-session", next(sessions.glob("*.json")).read_text())
        self.assertTrue((self.root / ".agent-team/runs/first/recovery/snapshot.json").exists())

    def test_error_exit_codes_and_session_fallback(self):
        for action, extra, code in (("precompact", [], 1),
                                    ("precompact", ["--fail-closed"], 2),
                                    ("session-start", [], 0),
                                    ("session-start", ["--invalid"], 0)):
            result = self.runner(self.root, "resume", "hook", action, *extra)
            self.assertEqual(result.returncode, code, result.stderr)
            if action == "session-start":
                self.assertIn("additionalContext", json.loads(result.stdout)["hookSpecificOutput"])

    def test_edited_owned_hook_is_not_overwritten(self):
        from agent_team.diagnostics import ValidationFailure
        manage_hooks(self.root, apply=True)
        target = self.root / ".claude/settings.local.json"
        data = json.loads(target.read_text())
        data["hooks"]["PreCompact"][0]["hooks"][0]["command"] += " changed"
        target.write_text(json.dumps(data))
        before = target.read_bytes()
        with self.assertRaises(ValidationFailure):
            manage_hooks(self.root, remove=True, apply=True)
        self.assertEqual(target.read_bytes(), before)
