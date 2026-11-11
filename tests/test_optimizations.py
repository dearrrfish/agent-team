"""Tests for role, template, and command optimizations."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_team.cli import main
from agent_team.config import DEFAULT_TEAM_TOML
from agent_team.templates import load_example_templates


class OptimizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.home = Path(self.home_dir.name)
        self.home_patcher = patch("pathlib.Path.home", return_value=self.home)
        self.home_patcher.start()
        # Initialize bare git repo for gitignore / commands that need it
        (self.root / ".git").mkdir()

    def tearDown(self) -> None:
        self.home_patcher.stop()
        self.home_dir.cleanup()
        self.temp_dir.cleanup()

    def test_default_team_toml_has_no_skill_sources_and_no_large_comments(self) -> None:
        self.assertNotIn("skill_sources", DEFAULT_TEAM_TOML)
        self.assertNotIn("# --- Complete codex profile example", DEFAULT_TEAM_TOML)

    def test_example_templates_generated_with_annotated_examples(self) -> None:
        templates = load_example_templates()
        # Roles
        for role in ("coordinator", "explorer", "implementer", "reviewer"):
            key = f"role/{role}/role.toml.example"
            self.assertIn(key, templates)
            self.assertNotIn(f"roles/{role}/role.toml.example", templates)
            content = templates[key]
            self.assertIn(f"Agent Team Role Definition Template: {role}", content)
            self.assertIn('schema_version = 1', content)
            self.assertIn(f'id = "{role}"', content)
            self.assertIn("# model_class", content)
            self.assertIn("# effort", content)
        # Profiles
        for target in ("codex", "claude", "antigravity", "pi"):
            key = f"profile/{target}.toml.example"
            self.assertIn(key, templates)
            self.assertNotIn(f"profiles/{target}.toml.example", templates)
            content = templates[key]
            self.assertIn(f"Agent Team Target Profile Template: {target}", content)
            self.assertIn('schema_version = 1', content)
            self.assertIn(f'id = "{target}"', content)
            self.assertIn("[presets.balanced]", content)

    def test_generate_template_selector(self) -> None:
        # Test generate template and generate templates
        with patch("sys.argv", ["agent-team", "generate", "template"]):
            with patch("pathlib.Path.cwd", return_value=self.root):
                code = main()
                self.assertEqual(code, 0)
        self.assertTrue((self.root / ".agent-team" / "templates" / "role" / "coordinator" / "role.toml.example").exists())
        self.assertTrue((self.root / ".agent-team" / "templates" / "profile" / "codex.toml.example").exists())
        self.assertFalse((self.root / ".agent-team" / "templates" / "prompt").exists())
        self.assertFalse((self.root / ".agent-team" / "templates" / "roles").exists())
        self.assertFalse((self.root / ".agent-team" / "templates" / "profiles").exists())
        self.assertFalse((self.root / ".agent-team" / "templates" / "prompts").exists())

    def test_init_diff_and_force_with_backup(self) -> None:
        # 1. First init creates team.toml
        with patch("sys.argv", ["agent-team", "init"]):
            with patch("pathlib.Path.cwd", return_value=self.root):
                self.assertEqual(main(), 0)

        team_file = self.root / ".agent-team" / "team.toml"
        self.assertTrue(team_file.exists())
        # Modify team.toml to create a diff
        team_file.write_text(team_file.read_text(encoding="utf-8") + "\n# custom modification\n", encoding="utf-8")

        # 2. Second init without force: should preserve existing, print diff, and return 0
        with patch("sys.argv", ["agent-team", "init"]):
            with patch("pathlib.Path.cwd", return_value=self.root):
                self.assertEqual(main(), 0)

        # 3. Init with --force but answering 'n': aborted, returns 1, should not overwrite
        with patch("sys.argv", ["agent-team", "init", "--force"]):
            with patch("pathlib.Path.cwd", return_value=self.root), patch("builtins.input", return_value="n"):
                self.assertEqual(main(), 1)
        self.assertIn("# custom modification", team_file.read_text(encoding="utf-8"))

        # 4. Init with --force --yes: should overwrite and create backup
        with patch("sys.argv", ["agent-team", "init", "--force", "--yes"]):
            with patch("pathlib.Path.cwd", return_value=self.root):
                self.assertEqual(main(), 0)
        self.assertNotIn("# custom modification", team_file.read_text(encoding="utf-8"))
        backups = list((self.root / ".agent-team").glob(".backup_*"))
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].is_file())
        self.assertIn("# custom modification", backups[0].read_text(encoding="utf-8"))

        # 5. Init with --force --yes --no-backup: should not create another backup
        team_file.write_text(team_file.read_text(encoding="utf-8") + "\n# mod2\n", encoding="utf-8")
        with patch("sys.argv", ["agent-team", "init", "--force", "--yes", "--no-backup"]):
            with patch("pathlib.Path.cwd", return_value=self.root):
                self.assertEqual(main(), 0)
        backups_after = list((self.root / ".agent-team").glob(".backup_*"))
        self.assertEqual(len(backups_after), 1)

    def test_install_diff_and_force_no_backup(self) -> None:
        # Initialize project
        with patch("sys.argv", ["agent-team", "init"]):
            with patch("pathlib.Path.cwd", return_value=self.root):
                self.assertEqual(main(), 0)

        # First install --apply
        with patch("sys.argv", ["agent-team", "install", "--target", "codex", "--apply"]):
            with patch("pathlib.Path.cwd", return_value=self.root):
                self.assertEqual(main(), 0)

        # Mutate an installed file
        installed_agent = self.root / ".codex" / "agents" / "coordinator.toml"
        self.assertTrue(installed_agent.exists())
        installed_agent.write_text(installed_agent.read_text(encoding="utf-8") + "\n# local modification\n", encoding="utf-8")

        # Install --diff: should show diff and return 2 because of drift without --force
        with patch("sys.argv", ["agent-team", "install", "--target", "codex", "--diff"]):
            with patch("pathlib.Path.cwd", return_value=self.root):
                self.assertEqual(main(), 2)

        # Install --diff --force: preview diff with force allowed returns 0
        with patch("sys.argv", ["agent-team", "install", "--target", "codex", "--diff", "--force"]):
            with patch("pathlib.Path.cwd", return_value=self.root):
                self.assertEqual(main(), 0)

        # Install --force without --yes, prompt answer 'n'
        with patch("sys.argv", ["agent-team", "install", "--target", "codex", "--apply", "--force"]):
            with patch("pathlib.Path.cwd", return_value=self.root), patch("builtins.input", return_value="n"):
                self.assertEqual(main(), 1)
        self.assertIn("# local modification", installed_agent.read_text(encoding="utf-8"))

        # Install --force --yes --no-backup: overwrites without backup
        with patch("sys.argv", ["agent-team", "install", "--target", "codex", "--apply", "--force", "--yes", "--no-backup"]):
            with patch("pathlib.Path.cwd", return_value=self.root):
                self.assertEqual(main(), 0)
        self.assertNotIn("# local modification", installed_agent.read_text(encoding="utf-8"))
        # Verify no backup directory created in .agent-team/backups
        backup_dir = self.root / ".agent-team" / "backups"
        self.assertFalse(backup_dir.exists())

    def test_generate_templates_scope_symlinks_and_copy(self) -> None:
        project_dir = self.root / "fake-project"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()

        # 1. Project generate templates by default generates symlinks pointing to user canonical templates
        with patch("sys.argv", ["agent-team", "generate", "templates"]):
            with patch("pathlib.Path.cwd", return_value=project_dir):
                self.assertEqual(main(), 0)

        user_template = self.home / ".agent-team" / "templates" / "role" / "coordinator" / "role.toml.example"
        proj_template = project_dir / ".agent-team" / "templates" / "role" / "coordinator" / "role.toml.example"
        self.assertTrue(user_template.is_file())
        self.assertTrue(proj_template.is_symlink())
        self.assertEqual(proj_template.resolve(), user_template.resolve())

        # 2. Project generate templates --copy creates regular files instead of symlinks
        with patch("sys.argv", ["agent-team", "generate", "templates", "--copy"]):
            with patch("pathlib.Path.cwd", return_value=project_dir):
                self.assertEqual(main(), 0)

        self.assertTrue(proj_template.is_file())
        self.assertFalse(proj_template.is_symlink())

    def test_builtin_review_policy_fallback_and_override(self) -> None:
        templates = load_example_templates()
        self.assertIn("review/REVIEW.md.example", templates)
        self.assertIn("Agent Team Review Policy Template: REVIEW.md", templates["review/REVIEW.md.example"])

        from agent_team.config import load_team_config
        from agent_team.run_state import prepare_review

        # Ensure project has team.toml and run
        with patch("sys.argv", ["agent-team", "init"]):
            with patch("pathlib.Path.cwd", return_value=self.root):
                main()
        with patch("sys.argv", ["agent-team", "run", "init", "--slug", "test-review", "--tier", "solo"]):
            with patch("pathlib.Path.cwd", return_value=self.root):
                main()

        config = load_team_config(self.root)

        # Case 1: No .agent-team/REVIEW.md file -> falls back to builtin template
        review_text = prepare_review(self.root, config, "test-review")
        self.assertIn("## Architecture assumptions and accepted risks", review_text)

        # Case 2: Custom .agent-team/REVIEW.md override exists
        custom_policy = self.root / ".agent-team" / "REVIEW.md"
        custom_policy.write_text("# Custom Org Review Policy Header\n", encoding="utf-8")
        review_text2 = prepare_review(self.root, config, "test-review")
        self.assertIn("# Custom Org Review Policy Header", review_text2)


if __name__ == "__main__":
    unittest.main()
