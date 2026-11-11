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


if __name__ == "__main__":
    unittest.main()
