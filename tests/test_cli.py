import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from agent_team.version import __base_version__

SOURCE = str(Path(__file__).parents[1] / "src")


class CliTests(unittest.TestCase):
    def _run(
        self,
        root: Path,
        *arguments: str,
        environment_overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = SOURCE
        environment.update(environment_overrides or {})
        return subprocess.run(
            [sys.executable, "-m", "agent_team", *arguments],
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_fresh_project_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init").returncode, 0)
            validation = self._run(root, "validate", "--format", "json")
            self.assertEqual(validation.returncode, 0, validation.stderr)
            self.assertTrue(json.loads(validation.stdout)["ok"])
            run = self._run(
                root, "run", "init", "--slug", "cli-run", "--tier", "assisted",
                "--model-preset", "quality",
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            render = self._run(
                root, "render", "--target", "codex", "--output", "dist", "--run", "cli-run"
            )
            self.assertEqual(render.returncode, 0, render.stderr)
            coordinator = tomllib.loads(
                (root / "dist" / ".codex" / "agents" / "coordinator.toml").read_text(encoding="utf-8")
            )
            self.assertEqual(coordinator["model"], "gpt-6-astra")
            preview = self._run(root, "install", "--target", "codex", "--run", "cli-run")
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn("preview only", preview.stdout)
            self.assertIn("quality preset", preview.stdout)
            doctor = self._run(root, "doctor", "--format", "json")
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            doctor_paths = {item["path"] for item in json.loads(doctor.stdout)["diagnostics"]}
            self.assertTrue({
                "clients.codex", "clients.claude", "clients.antigravity"
            }.issubset(doctor_paths))

    def test_invalid_config_has_nonzero_structured_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._run(root, "init")
            config = root / ".agent-team" / "team.toml"
            config.write_text(config.read_text(encoding="utf-8").replace("max_workers = 2", "max_workers = 8"), encoding="utf-8")
            result = self._run(root, "validate", "--format", "json")
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertTrue(any(item["path"] == "tiers.assisted.max_workers" for item in payload["diagnostics"]))

    def test_render_uses_only_an_explicit_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(Path(directory), "render", "--help")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--output OUTPUT", result.stdout)
            self.assertNotIn("--scope", result.stdout)

    def test_antigravity_user_install_uses_native_global_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as home:
            root = Path(directory)
            self.assertEqual(self._run(root, "init").returncode, 0)
            result = self._run(
                root,
                "install",
                "--target",
                "antigravity",
                "--scope",
                "user",
                environment_overrides={"HOME": home},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(".gemini/config/agents/coordinator/agent.md", result.stdout)
            self.assertIn(
                ".gemini/antigravity-cli/skills/team-workflow/SKILL.md",
                result.stdout,
            )

    def test_version_output_contains_commit_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(Path(directory), "--version")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertRegex(
                result.stdout.strip(),
                rf"^agent-team {re.escape(__base_version__)}\+[0-9a-zA-Z.]+$",
            )

    def test_version_output_with_env_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(
                Path(directory),
                "--version",
                environment_overrides={"AGENT_TEAM_COMMIT_HASH": "abcdef1"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(), f"agent-team {__base_version__}+abcdef1"
            )

    def test_init_upserts_prompts_and_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self._run(root, "init")
            self.assertEqual(result.returncode, 0, result.stderr)

            # verify team.toml
            self.assertTrue((root / ".agent-team" / "team.toml").is_file())

            # verify prompt templates
            prompts_dir = root / ".agent-team" / "templates" / "prompts"
            self.assertTrue(prompts_dir.is_dir())
            for name in ("plan.md", "coordinate.md", "review.md", "discovery.md"):
                prompt_file = prompts_dir / name
                self.assertTrue(prompt_file.is_file(), f"{name} is missing")
                self.assertGreater(len(prompt_file.read_text(encoding="utf-8")), 0)

            # verify gitignore entries
            gitignore_file = root / ".gitignore"
            self.assertTrue(gitignore_file.is_file())
            content = gitignore_file.read_text(encoding="utf-8")
            for entry in (".worktrees/", ".agent-team/runs/", ".agent-team/backups/", ".agent-team/install-state.json"):
                self.assertIn(entry, content)

    def test_init_is_idempotent_and_preserves_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init").returncode, 0)

            # modify team.toml
            team_toml = root / ".agent-team" / "team.toml"
            custom_config = team_toml.read_text(encoding="utf-8") + "\n# custom comment\n"
            team_toml.write_text(custom_config, encoding="utf-8")

            # modify one prompt template to verify update
            plan_prompt = root / ".agent-team" / "templates" / "prompts" / "plan.md"
            plan_prompt.write_text("modified", encoding="utf-8")

            # run init again
            second = self._run(root, "init")
            self.assertEqual(second.returncode, 0, second.stderr)

            # team.toml is preserved
            self.assertEqual(team_toml.read_text(encoding="utf-8"), custom_config)

            # modified prompt template was updated/upserted
            self.assertNotEqual(plan_prompt.read_text(encoding="utf-8"), "modified")

            # gitignore entries are not duplicated
            gitignore_content = (root / ".gitignore").read_text(encoding="utf-8")
            for entry in (".worktrees/", ".agent-team/runs/", ".agent-team/backups/", ".agent-team/install-state.json"):
                self.assertEqual(gitignore_content.count(entry), 1)

    def test_init_upserts_partial_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gitignore = root / ".gitignore"
            gitignore.write_text("node_modules/\n/.agent-team/runs/\n.worktrees", encoding="utf-8")

            result = self._run(root, "init")
            self.assertEqual(result.returncode, 0, result.stderr)

            content = gitignore.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("node_modules/\n/.agent-team/runs/\n.worktrees\n"))
            self.assertIn(".agent-team/backups/", content)
            self.assertIn(".agent-team/install-state.json", content)
            # Ensure existing entries were not duplicated
            lines = [line.strip().strip("/") for line in content.splitlines() if line.strip()]
            self.assertEqual(lines.count(".agent-team/runs"), 1)
            self.assertEqual(lines.count(".worktrees"), 1)


if __name__ == "__main__":
    unittest.main()
