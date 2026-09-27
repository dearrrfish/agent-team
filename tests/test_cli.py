import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from agent_team.templates import asset_text
from agent_team.version import __base_version__
from tests.test_customization import CUSTOM_ROLE

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
            for entry in (
                ".worktrees/", ".agent-team/runs/", ".agent-team/backups/",
                ".agent-team/install-state.json",
                "/.agent-team/templates/prompts/plan.md",
                "/.agent-team/templates/prompts/coordinate.md",
                "/.agent-team/templates/prompts/review.md",
                "/.agent-team/templates/prompts/discovery.md",
            ):
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
            for entry in (
                ".worktrees/", ".agent-team/runs/", ".agent-team/backups/",
                ".agent-team/install-state.json",
                "/.agent-team/templates/prompts/plan.md",
                "/.agent-team/templates/prompts/coordinate.md",
                "/.agent-team/templates/prompts/review.md",
                "/.agent-team/templates/prompts/discovery.md",
            ):
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

    def test_project_install_ignores_exact_native_files_for_each_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init").returncode, 0)
            ignore = root / ".gitignore"
            initial = ignore.read_text(encoding="utf-8")
            preview = self._run(root, "install", "--target", "codex")
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertEqual(ignore.read_text(encoding="utf-8"), initial)

            for target in ("codex", "claude", "antigravity"):
                applied = self._run(root, "install", "--target", target, "--apply")
                self.assertEqual(applied.returncode, 0, applied.stderr)

            rules = ignore.read_text(encoding="utf-8").splitlines()
            self.assertIn("/.codex/agents/coordinator.toml", rules)
            self.assertIn("/.claude/agents/coordinator.md", rules)
            self.assertIn("/.agents/agents/coordinator/agent.md", rules)
            self.assertIn("/.agents/skills/team-workflow/SKILL.md", rules)
            self.assertIn("/.claude/skills/team-workflow/SKILL.md", rules)
            self.assertNotIn(".agents/", rules)
            self.assertNotIn(".codex/", rules)
            self.assertNotIn(".claude/", rules)
            self.assertEqual(len([rule for rule in rules if rule.startswith("/.codex/agents/")]), 6)
            self.assertEqual(len([rule for rule in rules if rule.startswith("/.claude/agents/")]), 6)
            self.assertEqual(len([rule for rule in rules if rule.startswith("/.agents/agents/")]), 6)
            self.assertEqual(len([rule for rule in rules if rule.startswith("/.agents/skills/")]), 4)
            self.assertEqual(len([rule for rule in rules if rule.startswith("/.claude/skills/")]), 4)

            repeated = self._run(root, "install", "--target", "codex", "--apply")
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(ignore.read_text(encoding="utf-8").splitlines(), rules)

    def test_user_install_and_failed_project_install_do_not_change_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as home:
            root = Path(directory)
            self.assertEqual(self._run(root, "init").returncode, 0)
            ignore = root / ".gitignore"
            initial = ignore.read_bytes()
            user = self._run(
                root, "install", "--target", "codex", "--scope", "user", "--apply",
                environment_overrides={"HOME": home},
            )
            self.assertEqual(user.returncode, 0, user.stderr)
            self.assertEqual(ignore.read_bytes(), initial)

            conflict = root / ".codex" / "agents" / "coordinator.toml"
            conflict.parent.mkdir(parents=True)
            conflict.write_text("user content", encoding="utf-8")
            failed = self._run(root, "install", "--target", "codex", "--apply")
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(ignore.read_bytes(), initial)
            self.assertEqual(conflict.read_text(encoding="utf-8"), "user content")

    def test_ignore_write_failure_can_be_repaired_by_repeating_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init").returncode, 0)
            ignore = root / ".gitignore"
            saved = root / "saved-gitignore"
            ignore.rename(saved)
            ignore.mkdir()

            first = self._run(root, "install", "--target", "codex", "--apply")
            self.assertNotEqual(first.returncode, 0)
            self.assertIn("rerun the same install --apply command", first.stderr)
            self.assertTrue((root / ".agent-team" / "install-state.json").exists())
            self.assertTrue((root / ".codex" / "agents" / "coordinator.toml").exists())

            ignore.rmdir()
            saved.rename(ignore)
            second = self._run(root, "install", "--target", "codex", "--apply")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("/.codex/agents/coordinator.toml", ignore.read_text(encoding="utf-8"))

    def test_install_ignores_custom_sources_destinations_and_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init").returncode, 0)
            config = root / ".agent-team" / "team.toml"
            config.write_text(
                config.read_text(encoding="utf-8")
                .replace('role_sources = ["builtin:roles"]',
                         'role_sources = ["builtin:roles", "definitions/roles"]')
                .replace('skill_sources = ["builtin:skills"]',
                         'skill_sources = ["builtin:skills", "definitions/skills"]')
                .replace('codex = "builtin:codex"', 'codex = "definitions/codex.toml"'),
                encoding="utf-8",
            )
            profile = root / "definitions" / "codex.toml"
            profile.parent.mkdir(parents=True)
            profile.write_text(
                asset_text("definitions", "targets", "codex.toml")
                .replace('agent_destination = ".codex/agents"',
                         'agent_destination = ".codex/generated[agents]"'),
                encoding="utf-8",
            )
            role = root / "definitions" / "roles" / "analyst"
            role.mkdir(parents=True)
            (role / "role.toml").write_text(CUSTOM_ROLE, encoding="utf-8")
            (role / "instructions.md").write_text("Analyze the task.\n", encoding="utf-8")
            skill = root / "definitions" / "skills" / "local-skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("# Local skill\n", encoding="utf-8")

            first = self._run(root, "install", "--target", "codex", "--apply")
            self.assertEqual(first.returncode, 0, first.stderr)
            ignore = root / ".gitignore"
            rules = ignore.read_text(encoding="utf-8").splitlines()
            self.assertIn("/.codex/generated\\[agents\\]/analyst.toml", rules)
            self.assertIn("/.agents/skills/local-skill/SKILL.md", rules)
            self.assertNotIn("/definitions/roles/analyst/role.toml", rules)
            self.assertNotIn("/definitions/skills/local-skill/SKILL.md", rules)

            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    'role_sources = ["builtin:roles", "definitions/roles"]',
                    'role_sources = ["builtin:roles"]',
                ),
                encoding="utf-8",
            )
            second = self._run(root, "install", "--target", "codex", "--apply")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("stale", second.stdout)
            self.assertIn("/.codex/generated\\[agents\\]/analyst.toml", ignore.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
