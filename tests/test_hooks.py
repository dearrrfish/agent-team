import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_team.diagnostics import ValidationFailure
from agent_team.hooks import (
    hook_groups,
    hook_state_report,
    invocation_prefix,
    manage_hooks,
)
from tests import test_recovery


class HookTests(unittest.TestCase):
    setUp = test_recovery.RecoveryTests.setUp
    create_run = test_recovery.RecoveryTests.create_run

    def hook_state(self, apply=False):
        with patch.dict(os.environ, {"HOME": str(self.root / "isolated-home")}):
            return hook_state_report(self.root, apply=apply)

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
        groups = hook_groups(invocation="interpreter")
        payload = {"session_id": "private-session", "cwd": str(self.root), "hook_event_name": "PreCompact"}
        environment = os.environ.copy()
        environment["HOME"] = str(self.root / "isolated-home")
        for event in ("PreCompact", "SessionStart"):
            payload["hook_event_name"] = event
            command = groups[event][0]["hooks"][0]["command"]
            result = subprocess.run(command, shell=True, check=False, cwd=self.root, env=environment,
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
        manage_hooks(self.root, apply=True)
        target = self.root / ".claude/settings.local.json"
        data = json.loads(target.read_text())
        data["hooks"]["PreCompact"][0]["hooks"][0]["command"] += " changed"
        target.write_text(json.dumps(data))
        before = target.read_bytes()
        with self.assertRaises(ValidationFailure):
            manage_hooks(self.root, remove=True, apply=True)
        self.assertEqual(target.read_bytes(), before)

    def test_invocation_prefix_resolution(self):
        self.assertEqual(invocation_prefix(command_prefix="my-prefix --flag"), "my-prefix --flag")
        self.assertEqual(invocation_prefix(invocation="cli"), "agent-team")

        prefix = invocation_prefix(invocation="interpreter")
        self.assertIn("PYTHONPATH=", prefix)
        self.assertIn("-m agent_team", prefix)

        with patch("shutil.which", return_value="/etc/profiles/per-user/test/bin/agent-team"):
            self.assertEqual(invocation_prefix(invocation="auto"), "agent-team")

        with patch("shutil.which", return_value=None), patch("sys.executable", "/nix/store/abc-python3/bin/python3"):
            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                auto_prefix = invocation_prefix(invocation="auto")
            self.assertIn("PYTHONPATH=", auto_prefix)
            self.assertIn("warning: installing hooks with a nix store interpreter path", stderr.getvalue())

        with self.assertRaises(ValidationFailure):
            invocation_prefix(invocation="invalid")

    def test_cli_invocation_options_and_command_prefix(self):
        result_cli = self.runner(self.root, "resume", "hooks", "--print", "--invocation", "cli")
        self.assertEqual(result_cli.returncode, 0)
        self.assertIn('"command": "agent-team resume hook', result_cli.stdout)

        result_prefix = self.runner(self.root, "resume", "hooks", "--print", "--command-prefix", "my-exec agent-team")
        self.assertEqual(result_prefix.returncode, 0)
        self.assertIn('"command": "my-exec agent-team resume hook', result_prefix.stdout)

    def test_cli_user_scope_print_and_install(self):
        result = self.runner(self.root, "resume", "hooks", "--target", "antigravity",
                             "--scope", "user", "--print", "--invocation", "cli")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("antigravity-global-session-start", result.stdout)

        result = self.runner(self.root, "resume", "hooks", "--target", "antigravity",
                             "--scope", "user", "--install", "--apply", "--invocation", "cli")
        self.assertEqual(result.returncode, 0, result.stderr)
        home = self.root / "isolated-home"
        self.assertTrue((home / ".gemini/config/hooks.json").exists())
        self.assertTrue((home / ".agent-team/hooks-state-antigravity-user.json").exists())

        result = self.runner(self.root, "resume", "hooks", "--target", "claude",
                             "--scope", "user", "--print")
        self.assertEqual(result.returncode, 2)

    def test_hook_state_status_and_reconcile(self):
        self.assertEqual(self.hook_state(), "No hook state files.")

        manage_hooks(self.root, target="antigravity", apply=True, invocation="cli")
        state_path = self.root / ".agent-team" / "hooks-state-antigravity.json"
        report = self.hook_state()
        self.assertIn("ok", report)
        self.assertIn("antigravity, project", report)

        (self.root / ".agents" / "hooks.json").write_text("{}\n")
        report = self.hook_state()
        self.assertIn("remove", report)
        self.assertIn("Preview only", report)
        self.assertTrue(state_path.exists())

        report = self.hook_state(apply=True)
        self.assertIn("Updated 1 state file(s).", report)
        self.assertFalse(state_path.exists())

    def test_hook_state_legacy_migration(self):
        target = self.root / ".claude" / "settings.local.json"
        target.parent.mkdir()
        groups = hook_groups(invocation="cli")
        target.write_text(json.dumps({"hooks": groups}, indent=2) + "\n")
        legacy = self.root / ".agent-team" / "hooks-state.json"
        legacy.write_text(json.dumps({"path": ".claude/settings.local.json", "groups": groups},
                                     indent=2) + "\n")

        report = self.hook_state()
        self.assertIn("migrate", report)
        self.assertIn("hooks-state-claude.json", report)
        self.hook_state(apply=True)

        self.assertFalse(legacy.exists())
        migrated = self.root / ".agent-team" / "hooks-state-claude.json"
        record = json.loads(migrated.read_text())
        self.assertEqual(record["target"], "claude")
        self.assertEqual(record["scope"], "project")
        self.assertIn("ok", self.hook_state())

    def test_hook_state_modified_is_not_removed(self):
        manage_hooks(self.root, target="antigravity", apply=True, invocation="cli")
        hooks_path = self.root / ".agents" / "hooks.json"
        data = json.loads(hooks_path.read_text())
        data["agent-team"]["SessionStart"][0]["command"] += " changed"
        hooks_path.write_text(json.dumps(data))

        report = self.hook_state(apply=True)
        self.assertIn("manual", report)
        self.assertTrue((self.root / ".agent-team" / "hooks-state-antigravity.json").exists())

    def test_hook_state_superseded_legacy_is_removed(self):
        target = self.root / ".claude" / "settings.local.json"
        target.parent.mkdir()
        groups = hook_groups(invocation="cli")
        target.write_text(json.dumps({"hooks": groups}, indent=2) + "\n")
        record = json.dumps({"path": ".claude/settings.local.json", "groups": groups}, indent=2) + "\n"
        (self.root / ".agent-team" / "hooks-state.json").write_text(record)
        (self.root / ".agent-team" / "hooks-state-claude.json").write_text(record)

        report = self.hook_state()
        self.assertIn("remove", report)
        self.assertIn("hooks-state-claude.json exists", report)
        self.hook_state(apply=True)
        self.assertFalse((self.root / ".agent-team" / "hooks-state.json").exists())
        self.assertTrue((self.root / ".agent-team" / "hooks-state-claude.json").exists())

    def test_hook_state_user_scope_cleanup(self):
        home = self.root / "home"
        home.mkdir()
        with patch.dict(os.environ, {"HOME": str(home)}):
            manage_hooks(self.root, target="antigravity", scope="user", apply=True, invocation="cli")
            state_path = home / ".agent-team" / "hooks-state-antigravity-user.json"
            (home / ".gemini" / "config" / "hooks.json").unlink()

            self.assertIn("remove", hook_state_report(self.root))
            hook_state_report(self.root, apply=True)
            self.assertFalse(state_path.exists())

    def test_cli_hook_status_and_reconcile(self):
        result = self.runner(self.root, "resume", "hooks", "--status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "No hook state files.")

        manage_hooks(self.root, target="antigravity", apply=True, invocation="cli")
        result = self.runner(self.root, "resume", "hooks", "--status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

        (self.root / ".agents" / "hooks.json").write_text("{}\n")
        result = self.runner(self.root, "resume", "hooks", "--reconcile")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Preview only", result.stdout)
        self.assertTrue((self.root / ".agent-team" / "hooks-state-antigravity.json").exists())

        result = self.runner(self.root, "resume", "hooks", "--reconcile", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / ".agent-team" / "hooks-state-antigravity.json").exists())

    def test_migrate_nix_store_hook_to_stable_cli(self):
        target = self.root / ".claude" / "settings.local.json"
        state_path = self.root / ".agent-team" / "hooks-state.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        state_path.parent.mkdir(parents=True, exist_ok=True)

        old_cmd = "/nix/store/11111111-python3/bin/python3 -m agent_team resume hook"
        old_groups = {
            "PreCompact": [{"matcher": "manual|auto", "hooks": [{"type": "command", "command": f"{old_cmd} precompact", "timeout": 30, "onFailure": "continue"}]}],
            "SessionStart": [{"matcher": "compact", "hooks": [{"type": "command", "command": f"{old_cmd} session-start", "timeout": 30, "onFailure": "continue"}]}],
        }
        target.write_text(json.dumps({"hooks": old_groups}, indent=2) + "\n")
        state_path.write_text(json.dumps({"path": ".claude/settings.local.json", "groups": old_groups}, indent=2) + "\n")

        diff = manage_hooks(self.root, apply=True, invocation="cli")
        self.assertIn("-            \"command\": \"/nix/store/11111111-python3/bin/python3 -m agent_team resume hook precompact\",", diff)
        self.assertIn("+            \"command\": \"agent-team resume hook precompact\",", diff)

        installed = json.loads(target.read_text())
        self.assertEqual(installed["hooks"]["PreCompact"][0]["hooks"][0]["command"], "agent-team resume hook precompact")
        self.assertEqual(installed["hooks"]["SessionStart"][0]["hooks"][0]["command"], "agent-team resume hook session-start")

        state = json.loads(state_path.read_text())
        self.assertEqual(state["invocation"], "cli")
        self.assertEqual(state["groups"]["PreCompact"][0]["hooks"][0]["command"], "agent-team resume hook precompact")

    def test_codex_hooks_preview_install_and_remove(self):
        codex_path = self.root / ".codex" / "hooks.json"
        codex_state = self.root / ".agent-team" / "hooks-state-codex.json"
        claude_state = self.root / ".agent-team" / "hooks-state-claude.json"

        groups = hook_groups(invocation="cli", target="codex")
        self.assertEqual(groups["SessionStart"][0]["hooks"][0]["additionalContextLimit"], 0)
        self.assertNotIn("onFailure", groups["SessionStart"][0]["hooks"][0])

        preview = manage_hooks(self.root, target="codex", invocation="cli")
        self.assertIn(".codex/hooks.json", preview)
        self.assertFalse(codex_path.exists())

        manage_hooks(self.root, target="codex", invocation="cli", apply=True)
        installed = json.loads(codex_path.read_text())
        self.assertEqual(installed["hooks"]["PreCompact"][0]["hooks"][0]["command"],
                         "agent-team resume hook precompact")
        self.assertEqual(installed["hooks"]["SessionStart"][0]["hooks"][0]["additionalContextLimit"], 0)
        state = json.loads(codex_state.read_text())
        self.assertEqual(state["target"], "codex")
        self.assertFalse(claude_state.exists())

        self.assertEqual(manage_hooks(self.root, target="codex", invocation="cli", apply=True), "No hook changes.")
        manage_hooks(self.root, target="codex", invocation="cli", remove=True, apply=True)
        self.assertEqual(json.loads(codex_path.read_text()), {})

    def test_codex_and_claude_state_are_isolated(self):
        manage_hooks(self.root, apply=True, invocation="cli")
        manage_hooks(self.root, target="codex", apply=True, invocation="cli")
        claude = json.loads((self.root / ".claude/settings.local.json").read_text())
        codex = json.loads((self.root / ".codex/hooks.json").read_text())
        self.assertNotIn("additionalContextLimit", claude["hooks"]["SessionStart"][0]["hooks"][0])
        self.assertEqual(codex["hooks"]["SessionStart"][0]["hooks"][0]["additionalContextLimit"], 0)
        manage_hooks(self.root, remove=True, apply=True)
        self.assertEqual(json.loads((self.root / ".codex/hooks.json").read_text()),
                         json.loads(json.dumps(codex)))

    def test_codex_payload_field_compatibility(self):
        self.create_run()
        for payload in ({"hookEventName": "SessionStart", "threadId": "codex-thread", "cwd": str(self.root)},
                        {"hook_event_name": "SessionStart", "session_id": "codex-thread", "cwd": str(self.root)}):
            result = subprocess.run(
                [sys.executable, "-m", "agent_team", "resume", "hook", "session-start"],
                shell=False, check=False, cwd=self.root,
                env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src"),
                     "HOME": str(self.root / "isolated-home")},
                input=json.dumps(payload), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("additionalContext", json.loads(result.stdout)["hookSpecificOutput"])

    def test_antigravity_hooks_preview_install_and_remove(self):
        hooks_path = self.root / ".agents" / "hooks.json"
        state_path = self.root / ".agent-team" / "hooks-state-antigravity.json"

        groups = hook_groups(invocation="cli", target="antigravity")
        self.assertEqual(list(groups), ["agent-team"])
        self.assertEqual(groups["agent-team"]["SessionStart"][0]["command"],
                         "agent-team resume hook antigravity-session-start")
        self.assertNotIn("matcher", groups["agent-team"]["SessionStart"][0])

        preview = manage_hooks(self.root, target="antigravity", invocation="cli")
        self.assertIn(".agents/hooks.json", preview)
        self.assertFalse(hooks_path.exists())

        manage_hooks(self.root, target="antigravity", invocation="cli", apply=True)
        installed = json.loads(hooks_path.read_text())
        self.assertEqual(installed["agent-team"]["SessionStart"][0]["command"],
                         "agent-team resume hook antigravity-session-start")
        state = json.loads(state_path.read_text())
        self.assertEqual(state["namespace"], "agent-team")
        self.assertEqual(state["target"], "antigravity")

        self.assertEqual(manage_hooks(self.root, target="antigravity", invocation="cli", apply=True),
                         "No hook changes.")
        manage_hooks(self.root, target="antigravity", invocation="cli", remove=True, apply=True)
        self.assertEqual(json.loads(hooks_path.read_text()), {})

    def test_antigravity_namespace_conflict_is_refused(self):
        hooks_path = self.root / ".agents" / "hooks.json"
        hooks_path.parent.mkdir(parents=True)
        hooks_path.write_text(json.dumps({"agent-team": {"SessionStart": [{"type": "command",
                                                                           "command": "other"}]}}))
        with self.assertRaises(ValidationFailure):
            manage_hooks(self.root, target="antigravity", apply=True, invocation="cli")

    def test_antigravity_user_scope_install_and_remove(self):
        home = self.root / "home"
        home.mkdir()
        hooks_path = home / ".gemini" / "config" / "hooks.json"
        state_path = home / ".agent-team" / "hooks-state-antigravity-user.json"
        with patch.dict(os.environ, {"HOME": str(home)}):
            groups = hook_groups(invocation="cli", target="antigravity", scope="user")
            self.assertEqual(groups["agent-team"]["SessionStart"][0]["command"],
                             "agent-team resume hook antigravity-global-session-start")

            preview = manage_hooks(self.root, target="antigravity", scope="user", invocation="cli")
            self.assertIn(".gemini/config/hooks.json", preview)
            self.assertFalse(hooks_path.exists())

            manage_hooks(self.root, target="antigravity", scope="user", invocation="cli", apply=True)
            installed = json.loads(hooks_path.read_text())
            self.assertEqual(installed["agent-team"]["SessionStart"][0]["command"],
                             "agent-team resume hook antigravity-global-session-start")
            state = json.loads(state_path.read_text())
            self.assertEqual(state["scope"], "user")
            self.assertEqual(state["path"], ".gemini/config/hooks.json")
            self.assertFalse((self.root / ".agents" / "hooks.json").exists())

            self.assertEqual(manage_hooks(self.root, target="antigravity", scope="user",
                                          invocation="cli", apply=True), "No hook changes.")
            manage_hooks(self.root, target="antigravity", scope="user", invocation="cli",
                         remove=True, apply=True)
            self.assertEqual(json.loads(hooks_path.read_text()), {})

    def test_antigravity_user_scope_rejects_other_targets(self):
        for target in ("claude", "codex"):
            with self.assertRaises(ValidationFailure):
                hook_groups(target=target, scope="user")
            with self.assertRaises(ValidationFailure):
                manage_hooks(self.root, target=target, scope="user", apply=True)
        with self.assertRaises(ValidationFailure):
            manage_hooks(self.root, target="antigravity", scope="global", apply=True)

    def test_antigravity_global_payload_injects_steps_and_stays_silent(self):
        self.create_run()
        config_dir = self.root / "home" / ".gemini" / "config"
        config_dir.mkdir(parents=True)
        environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src"),
                       "HOME": str(self.root / "isolated-home")}

        def run(workspace: Path) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, "-m", "agent_team", "resume", "hook",
                 "antigravity-global-session-start"],
                shell=False, check=False, cwd=config_dir, env=environment, text=True,
                capture_output=True,
                input=json.dumps({"conversationId": "agy-global", "workspacePaths": [str(workspace)]}))

        result = run(self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        steps = json.loads(result.stdout)["injectSteps"]
        self.assertIn("first", steps[0]["systemMessage"]["systemMessage"])

        plain = self.root / "plain-project"
        plain.mkdir()
        result = run(plain)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_antigravity_payload_injects_steps(self):
        self.create_run()
        hooks_dir = self.root / ".agents"
        hooks_dir.mkdir()
        payload = {"conversationId": "agy-conversation", "workspacePaths": [str(self.root)],
                   "transcriptPath": str(self.root / "transcript.jsonl")}
        # Antigravity launches hooks from the hooks.json directory, not the
        # workspace root.
        result = subprocess.run(
            [sys.executable, "-m", "agent_team", "resume", "hook", "antigravity-session-start"],
            shell=False, check=False, cwd=hooks_dir,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src"),
                 "HOME": str(self.root / "isolated-home")},
            input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        steps = json.loads(result.stdout)["injectSteps"]
        self.assertIn("first", steps[0]["systemMessage"]["systemMessage"])
