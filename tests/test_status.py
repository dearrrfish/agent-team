from __future__ import annotations

import curses
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_team.config import load_team_config
from agent_team.status import (
    collect_team_status,
    detect_active_target,
    format_json_status,
    format_text_status,
    run_status_tui,
)

SOURCE = str(Path(__file__).parents[1] / "src")


class TestStatus(unittest.TestCase):
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
        res = self._run(self.repo, "run", "init", "--slug", "status-test-run", "--tier", "assisted")
        self.assertEqual(res.returncode, 0, res.stderr)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_collect_team_status(self) -> None:
        report = collect_team_status(self.repo)
        self.assertTrue(report.version)
        self.assertEqual(report.root, self.repo)
        self.assertTrue(report.project_config_exists)
        self.assertEqual(report.run_root, ".agent-team/runs")
        self.assertEqual(report.worktree_root, ".worktrees")
        self.assertEqual(len(report.targets), 4)
        self.assertTrue(len(report.roles) >= 6)
        self.assertTrue(any(r.slug == "status-test-run" for r in report.runs))

        # Check serialization
        data = report.to_dict()
        self.assertEqual(data["root"], str(self.repo))
        self.assertIn("targets", data)
        self.assertIn("roles", data)

    def test_detect_active_target(self) -> None:
        config = load_team_config(self.repo)

        # Explicit target
        self.assertEqual(detect_active_target(self.repo, config, "claude"), "claude")

        # Environment detection
        with patch.dict(os.environ, {"PI_SESSION_ID": "pi-123"}):
            self.assertEqual(detect_active_target(self.repo, config), "pi")

        with patch.dict(os.environ, {"CLAUDE_PROJECT_ROOT": "/some/path"}, clear=True):
            self.assertEqual(detect_active_target(self.repo, config), "claude")

        with patch.dict(os.environ, {"CODEX_HOME": "/some/codex"}, clear=True):
            self.assertEqual(detect_active_target(self.repo, config), "codex")

    def test_format_text_status(self) -> None:
        # Add cross-tool runner to implementer
        team_toml = self.repo / ".agent-team" / "team.toml"
        team_toml.write_text(
            team_toml.read_text(encoding="utf-8") + "\n[roles.implementer]\nrunner = 'codex'\n",
            encoding="utf-8",
        )

        report = collect_team_status(self.repo, requested_target="claude")
        text = format_text_status(report)

        self.assertIn("== Agent Team Overview ==", text)
        self.assertIn("Active Target:        claude", text)
        self.assertIn("== Roles & Dispatch Routing ==", text)
        self.assertIn("codex [CROSS]", text)
        self.assertIn("== Model Presets for Active Target (claude) ==", text)
        self.assertIn("== Recent Runs & Active Worktrees ==", text)
        self.assertIn("status-test-run", text)

    def test_format_json_status(self) -> None:
        report = collect_team_status(self.repo)
        raw_json = format_json_status(report)
        parsed = json.loads(raw_json)
        self.assertEqual(parsed["root"], str(self.repo))
        self.assertEqual(parsed["run_root"], ".agent-team/runs")
        self.assertIsInstance(parsed["roles"], list)

    def test_cli_status_text_and_json(self) -> None:
        res = self._run(self.repo, "status", "--format", "text")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("== Agent Team Overview ==", res.stdout)

        res_json = self._run(self.repo, "status", "--format", "json")
        self.assertEqual(res_json.returncode, 0, res_json.stderr)
        data = json.loads(res_json.stdout)
        self.assertEqual(data["root"], str(self.repo))

        res_target = self._run(self.repo, "status", "--target", "claude", "--format", "text")
        self.assertEqual(res_target.returncode, 0, res_target.stderr)
        self.assertIn("Active Target:        claude", res_target.stdout)

    def test_run_status_tui_fallback(self) -> None:
        report = collect_team_status(self.repo)
        # Mock curses.wrapper raising curses.error (simulating non-interactive terminal)
        with patch("curses.wrapper", side_effect=curses.error("mock error")):
            ret = run_status_tui(report)
            self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main()
