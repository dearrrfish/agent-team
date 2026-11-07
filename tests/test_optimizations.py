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
        self.root = Path(self.temp_dir.name)
        # Initialize bare git repo for gitignore / commands that need it
        (self.root / ".git").mkdir()

    def tearDown(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
