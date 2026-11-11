from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_team.config import load_roles, load_team_config
from agent_team.diagnostics import ValidationFailure
from agent_team.dispatch import (
    DispatchRequest,
    build_dispatch_plan,
    execute_dispatch,
    resolve_runner_for_role,
    sanitize_dispatch_env,
)

SOURCE = str(Path(__file__).parents[1] / "src")


class TestDispatch(unittest.TestCase):
    def _run(self, root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = SOURCE
        environment["HOME"] = str(root / "isolated-home")
        return subprocess.run(
            ["python3", "-m", "agent_team", *arguments],
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name).resolve()
        subprocess.run(["git", "init", "-b", "main", str(self.repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Tester"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "tester@example.com"], check=True)
        (self.repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "initial commit"], check=True)

        # Initialize agent-team in project
        res = self._run(self.repo, "init", "--scope", "project")
        self.assertEqual(res.returncode, 0, res.stderr)

        # Initialize a run
        res = self._run(self.repo, "run", "init", "--slug", "dispatch-test-run", "--tier", "team")
        self.assertEqual(res.returncode, 0, res.stderr)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_runner_config_and_validation(self) -> None:
        team_toml = self.repo / ".agent-team" / "team.toml"
        content = team_toml.read_text(encoding="utf-8")

        # Configure runner for implementer and reviewer
        updated = content + "\n[roles.implementer]\nrunner = \"codex\"\n\n[roles.reviewer]\nrunner = \"claude\"\n"
        team_toml.write_text(updated, encoding="utf-8")

        config = load_team_config(self.repo)
        roles = {r.role_id: r for r in load_roles(config, self.repo)}
        self.assertEqual(roles["implementer"].runner, "codex")
        self.assertEqual(roles["reviewer"].runner, "claude")
        self.assertIsNone(roles["explorer"].runner)

        # Verify resolve_runner_for_role priority
        self.assertEqual(resolve_runner_for_role(roles["implementer"], config), "codex")
        self.assertEqual(resolve_runner_for_role(roles["implementer"], config, "pi"), "pi")
        self.assertEqual(resolve_runner_for_role(roles["explorer"], config), "codex")

        # Invalid runner should fail validation
        bad = content + "\n[roles.implementer]\nrunner = \"invalid-runner\"\n"
        team_toml.write_text(bad, encoding="utf-8")
        with self.assertRaises(ValidationFailure) as ctx:
            load_team_config(self.repo)
        self.assertTrue(any("must be one of" in d.message for d in ctx.exception.diagnostics))

    def test_build_dispatch_plan_implementer(self) -> None:
        config = load_team_config(self.repo)
        req = DispatchRequest(
            root=self.repo,
            config=config,
            slug="dispatch-test-run",
            role_id="implementer",
            runner="codex",
            instruction="Implement feature X",
        )
        plan = build_dispatch_plan(req)
        self.assertEqual(plan.runner, "codex")
        self.assertEqual(plan.role_id, "implementer")
        self.assertIn("codex", plan.command[0])
        self.assertIn("workspace-write", plan.command)
        self.assertTrue(plan.report_path.as_posix().endswith("reports/implementer-adhoc.md"))
        self.assertIn("Implement feature X", plan.prompt)
        self.assertIn("## Report Contract", plan.prompt)
        self.assertIn("## Subagent Directives", plan.prompt)
        # Default should NOT mention AskHuman
        self.assertNotIn("AskHuman", plan.prompt)

    def test_askhuman_integration_prompt_injection(self) -> None:
        config = load_team_config(self.repo)
        self.assertFalse(config.integrations.askhuman)

        # 1. Explicitly enable via request
        req_enabled = DispatchRequest(
            root=self.repo,
            config=config,
            slug="dispatch-test-run",
            role_id="implementer",
            askhuman=True,
        )
        plan_enabled = build_dispatch_plan(req_enabled)
        self.assertIn(
            "- **This protocol does not apply to subagents. You are a subagent and must not use AskHuman.**",
            plan_enabled.prompt,
        )

        # 2. Config level enable
        team_toml = self.repo / ".agent-team" / "team.toml"
        content = team_toml.read_text(encoding="utf-8")
        if "askhuman = false" in content:
            updated = content.replace("askhuman = false", "askhuman = true")
        else:
            updated = content + "\n[integrations]\naskhuman = true\n"
        team_toml.write_text(updated, encoding="utf-8")
        config_with_askhuman = load_team_config(self.repo)
        self.assertTrue(config_with_askhuman.integrations.askhuman)

        req_config_default = DispatchRequest(
            root=self.repo,
            config=config_with_askhuman,
            slug="dispatch-test-run",
            role_id="implementer",
        )
        plan_config_default = build_dispatch_plan(req_config_default)
        self.assertIn(
            "- **This protocol does not apply to subagents. You are a subagent and must not use AskHuman.**",
            plan_config_default.prompt,
        )

        # 3. Explicitly disable overrides config
        req_explicit_disabled = DispatchRequest(
            root=self.repo,
            config=config_with_askhuman,
            slug="dispatch-test-run",
            role_id="implementer",
            askhuman=False,
        )
        plan_explicit_disabled = build_dispatch_plan(req_explicit_disabled)
        self.assertNotIn("AskHuman", plan_explicit_disabled.prompt)

        # 4. CLI test via --askhuman
        res = self._run(
            self.repo,
            "dispatch",
            "--slug",
            "dispatch-test-run",
            "--role",
            "implementer",
            "--askhuman",
            "--dry-run",
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("AskHuman", res.stdout)

        disabled = self._run(
            self.repo, "dispatch", "--slug", "dispatch-test-run",
            "--no-askhuman", "--dry-run",
        )
        self.assertEqual(disabled.returncode, 0, disabled.stderr)
        self.assertNotIn("AskHuman", disabled.stdout)

        reviewer = build_dispatch_plan(DispatchRequest(
            root=self.repo, config=config_with_askhuman,
            slug="dispatch-test-run", role_id="reviewer",
        ))
        self.assertIn("must not use AskHuman", reviewer.prompt)

    def test_askhuman_config_rejects_invalid_values(self) -> None:
        team_toml = self.repo / ".agent-team" / "team.toml"
        content = team_toml.read_text(encoding="utf-8")
        for value in ('"true"', '1'):
            with self.subTest(value=value):
                team_toml.write_text(
                    content.replace("askhuman = false", f"askhuman = {value}"),
                    encoding="utf-8",
                )
                with self.assertRaises(ValidationFailure) as ctx:
                    load_team_config(self.repo)
                self.assertTrue(any(
                    d.path == "integrations.askhuman" for d in ctx.exception.diagnostics
                ))
        team_toml.write_text(content + '\n[integrations.unknown]\n', encoding="utf-8")
        with self.assertRaises(ValidationFailure):
            load_team_config(self.repo)

    def test_build_dispatch_plan_reviewer(self) -> None:
        config = load_team_config(self.repo)
        req = DispatchRequest(
            root=self.repo,
            config=config,
            slug="dispatch-test-run",
            role_id="reviewer",
            runner="claude",
        )
        plan = build_dispatch_plan(req)
        self.assertEqual(plan.runner, "claude")
        self.assertEqual(plan.role_id, "reviewer")
        self.assertEqual(plan.command[0], "claude")
        self.assertIn("--permission-mode", plan.command)
        self.assertIn("dontAsk", plan.command)
        self.assertTrue(plan.report_path.as_posix().endswith("review.md"))
        self.assertIn("Review Packet:", plan.prompt)
        self.assertIn("## Review Contract", plan.prompt)

    def test_build_dispatch_plan_with_task_and_worktree(self) -> None:
        # Add task T-001 to run.toml
        run_toml = self.repo / ".agent-team" / "runs" / "dispatch-test-run" / "run.toml"
        run_data = run_toml.read_text(encoding="utf-8")
        task_block = (
            '\n[[tasks]]\nid = "T-001"\ntitle = "Build widget"\nrole = "implementer"\n'
            'status = "ready"\nowned_paths = ["src/widget.py"]\n'
        )
        run_toml.write_text(run_data + task_block, encoding="utf-8")

        config = load_team_config(self.repo)
        req = DispatchRequest(
            root=self.repo,
            config=config,
            slug="dispatch-test-run",
            role_id="implementer",
            task_id="T-001",
            runner="pi",
            worktree=True,
        )
        plan = build_dispatch_plan(req)
        self.assertEqual(plan.runner, "pi")
        self.assertEqual(plan.task_id, "T-001")
        self.assertTrue(plan.report_path.as_posix().endswith("reports/T-001.md"))
        self.assertIsNotNone(plan.worktree_path)
        self.assertTrue(str(plan.worktree_path).endswith("dispatch-test-run-T-001"))
        self.assertEqual(plan.cwd, plan.worktree_path)
        self.assertIn("src/widget.py", plan.prompt)

    def test_cli_dispatch_dry_run(self) -> None:
        # Text format
        res = self._run(
            self.repo,
            "dispatch",
            "--slug", "dispatch-test-run",
            "--role", "implementer",
            "--runner", "codex",
            "--dry-run",
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Dispatch Plan for Run: dispatch-test-run", res.stdout)
        self.assertIn("Role:        implementer", res.stdout)
        self.assertIn("Runner:      codex", res.stdout)

        # JSON format
        res_json = self._run(
            self.repo,
            "dispatch",
            "--slug", "dispatch-test-run",
            "--role", "reviewer",
            "--runner", "claude",
            "--format", "json",
            "--dry-run",
        )
        self.assertEqual(res_json.returncode, 0, res_json.stderr)
        data = json.loads(res_json.stdout)
        self.assertEqual(data["runner"], "claude")
        self.assertEqual(data["role"], "reviewer")
        self.assertTrue(data["report_path"].endswith("review.md"))

    def test_execute_dispatch_missing_executable(self) -> None:
        config = load_team_config(self.repo)
        req = DispatchRequest(
            root=self.repo,
            config=config,
            slug="dispatch-test-run",
            role_id="implementer",
            runner="codex",
        )
        plan = build_dispatch_plan(req)

        with patch("shutil.which", return_value=None):
            result = execute_dispatch(self.repo, config, "dispatch-test-run", plan)
            self.assertFalse(result.success)
            self.assertEqual(result.returncode, 127)
            self.assertIn("not found on PATH", result.stderr)

    def test_execute_dispatch_report_auto_extraction(self) -> None:
        config = load_team_config(self.repo)
        req = DispatchRequest(
            root=self.repo,
            config=config,
            slug="dispatch-test-run",
            role_id="implementer",
            task_id="T-002",
            runner="codex",
        )
        plan = build_dispatch_plan(req)

        stdout_report = (
            "# Agent report: T-002\n\n"
            "## Status\nCompleted widget implementation.\n\n"
            "## Verification\nRan pytest with 5 passed tests.\n\n"
            "## Changed files\n- src/widget.py\n\n"
            "## Residual risks\nNone.\n"
        )

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = stdout_report
        mock_proc.stderr = ""

        with patch("shutil.which", return_value="/fake/bin/codex"), patch("subprocess.run", return_value=mock_proc):
            result = execute_dispatch(self.repo, config, "dispatch-test-run", plan)
            self.assertTrue(result.success)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(plan.report_path.is_file())
            content = plan.report_path.read_text(encoding="utf-8")
            self.assertIn("## Status\nCompleted widget implementation.", content)
            self.assertTrue(result.report_synced)


    def test_sanitize_dispatch_env_cross_tool_and_auth(self) -> None:
        dirty_env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/user",
            "ANTHROPIC_API_KEY": "sk-ant-valid-key",
            "OPENAI_API_KEY": "sk-oai-valid-key",
            "CLAUDE_CODE": "1",
            "CLAUDE_PROJECT_ROOT": "/some/project",
            "CLAUDE_SESSION_ID": "parent-claude-sess",
            "PI_SESSION_ID": "parent-pi-sess",
            "PI_CODING_AGENT": "1",
            "CODEX_SESSION": "parent-codex-sess",
            "CODEX_SANDBOX": "workspace-write",
            "ANTIGRAVITY_SESSION_ID": "parent-ag-sess",
        }

        # Dispatching to codex
        clean_env = sanitize_dispatch_env(
            base_env=dirty_env,
            target_runner="codex",
            slug="test-slug",
            role_id="implementer",
            task_id="task-1",
        )

        # Alien client markers must be removed
        self.assertNotIn("CLAUDE_CODE", clean_env)
        self.assertNotIn("CLAUDE_PROJECT_ROOT", clean_env)
        self.assertNotIn("CLAUDE_SESSION_ID", clean_env)
        self.assertNotIn("PI_SESSION_ID", clean_env)
        self.assertNotIn("PI_CODING_AGENT", clean_env)
        self.assertNotIn("ANTIGRAVITY_SESSION_ID", clean_env)

        # Target runner's own parent session marker must be removed
        self.assertNotIn("CODEX_SESSION", clean_env)

        # Essential paths and API keys must be retained
        self.assertEqual(clean_env["PATH"], "/usr/bin:/bin")
        self.assertEqual(clean_env["HOME"], "/home/user")
        self.assertEqual(clean_env["ANTHROPIC_API_KEY"], "sk-ant-valid-key")
        self.assertEqual(clean_env["OPENAI_API_KEY"], "sk-oai-valid-key")

        # Injected metadata must be present
        self.assertEqual(clean_env["AGENT_TEAM_ACTIVE_TARGET"], "codex")
        self.assertEqual(clean_env["AGENT_TEAM_RUNNER"], "codex")
        self.assertEqual(clean_env["AGENT_TEAM_RUN_SLUG"], "test-slug")
        self.assertEqual(clean_env["AGENT_TEAM_ROLE_ID"], "implementer")
        self.assertEqual(clean_env["AGENT_TEAM_TASK_ID"], "task-1")
        self.assertEqual(clean_env["AGENT_TEAM_DISPATCH_DEPTH"], "1")

    def test_sanitize_dispatch_env_same_tool_fresh_session(self) -> None:
        parent_claude_env = {
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "CLAUDE_CODE": "1",
            "CLAUDE_SESSION_ID": "parent-session-xyz",
            "CLAUDE_CONVERSATION_ID": "parent-conv-123",
        }
        clean_env = sanitize_dispatch_env(
            base_env=parent_claude_env,
            target_runner="claude",
            slug="test-slug",
            role_id="reviewer",
        )
        self.assertNotIn("CLAUDE_SESSION_ID", clean_env)
        self.assertNotIn("CLAUDE_CONVERSATION_ID", clean_env)
        self.assertEqual(clean_env["ANTHROPIC_API_KEY"], "sk-ant-test")
        self.assertEqual(clean_env["AGENT_TEAM_ACTIVE_TARGET"], "claude")

    def test_sanitize_dispatch_env_recursion_guard(self) -> None:
        nested_env = {
            "AGENT_TEAM_DISPATCH_DEPTH": "1",
        }
        with self.assertRaises(ValidationFailure) as ctx:
            sanitize_dispatch_env(
                base_env=nested_env,
                target_runner="codex",
                slug="test-slug",
                role_id="worker",
                max_depth=1,
            )
        self.assertTrue(
            any("cannot recursively dispatch child agents" in d.message for d in ctx.exception.diagnostics)
        )


if __name__ == "__main__":
    unittest.main()
