from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent_team.cli import main
from agent_team.config import (
    load_team_config,
    project_root,
)


class HierarchyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base = Path(self.temp_dir.name)
        self.home = self.base / "home"
        self.user_config = self.home / ".agent-team"
        self.user_config.mkdir(parents=True)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir(parents=True)

        self.home_patch = patch("pathlib.Path.home", return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)

    def write_user(self, content: str) -> None:
        (self.user_config / "team.toml").write_text(content, encoding="utf-8")

    def test_clean_project_without_team_toml_inherits_user_defaults(self) -> None:
        project = self.workspace / "clean-project"
        project.mkdir()
        self.write_user("""schema_version = 1
default_tier = "team"
default_model_preset = "quality"
enabled_targets = ["claude"]

[model_presets.claude.quality.models]
fast = "user-fast"
""")
        config = load_team_config(project)
        self.assertEqual(config.default_tier, "team")
        self.assertEqual(config.default_model_preset, "quality")
        self.assertEqual(config.enabled_targets, ("claude",))
        self.assertEqual(config.model_presets["claude"]["quality"].models["fast"], "user-fast")
        self.assertEqual(config.field_origins["default_tier"], "user")
        self.assertEqual(config.field_origins["model_presets.claude.quality.models.fast"], "user")

    def test_clean_project_without_team_toml_and_without_user_inherits_builtin(self) -> None:
        project = self.workspace / "bare-project"
        project.mkdir()
        config = load_team_config(project)
        self.assertEqual(config.default_tier, "adaptive")
        self.assertEqual(config.default_model_preset, "balanced")
        self.assertEqual(config.enabled_targets, ("codex", "claude", "antigravity"))
        self.assertEqual(config.field_origins["default_tier"], "builtin")

    def test_project_without_team_toml_inherits_ancestor_configuration(self) -> None:
        parent = self.workspace / "parent"
        child = parent / "child"
        child.mkdir(parents=True)
        (parent / ".agent-team").mkdir()
        (parent / ".agent-team" / "team.toml").write_text("""schema_version = 1
default_tier = "solo"
[model_presets.codex.balanced.models]
fast = "parent-fast"
""", encoding="utf-8")

        config = load_team_config(child)
        self.assertEqual(config.default_tier, "solo")
        self.assertEqual(config.model_presets["codex"]["balanced"].models["fast"], "parent-fast")
        self.assertEqual(config.field_origins["default_tier"], "ancestor")
        self.assertEqual(config.field_origins["model_presets.codex.balanced.models.fast"], "ancestor")

    def test_multi_level_ancestor_and_user_layering(self) -> None:
        level1 = self.workspace / "org"
        level2 = level1 / "team"
        project = level2 / "app"
        project.mkdir(parents=True)

        self.write_user("""schema_version = 1
[model_presets.codex.balanced.models]
fast = "user-fast"
balanced = "user-balanced"
deep = "user-deep"
""")
        (level1 / ".agent-team").mkdir()
        (level1 / ".agent-team" / "team.toml").write_text("""schema_version = 1
[model_presets.codex.balanced.models]
balanced = "org-balanced"
""", encoding="utf-8")

        (level2 / ".agent-team").mkdir()
        (level2 / ".agent-team" / "team.toml").write_text("""schema_version = 1
[model_presets.codex.balanced.models]
deep = "team-deep"
""", encoding="utf-8")

        config = load_team_config(project)
        models = config.model_presets["codex"]["balanced"].models
        self.assertEqual(models["fast"], "user-fast")
        self.assertEqual(models["balanced"], "org-balanced")
        self.assertEqual(models["deep"], "team-deep")
        self.assertEqual(config.field_origins["model_presets.codex.balanced.models.fast"], "user")
        self.assertEqual(config.field_origins["model_presets.codex.balanced.models.balanced"], "ancestor")
        self.assertEqual(config.field_origins["model_presets.codex.balanced.models.deep"], "ancestor")

    def test_ancestor_with_inherit_user_defaults_false_isolates_from_user(self) -> None:
        parent = self.workspace / "parent"
        child = parent / "child"
        child.mkdir(parents=True)

        self.write_user("""schema_version = 1
default_tier = "team"
[model_presets.codex.balanced.models]
fast = "user-fast"
""")
        (parent / ".agent-team").mkdir()
        (parent / ".agent-team" / "team.toml").write_text("""schema_version = 1
inherit_user_defaults = false
default_tier = "solo"
""", encoding="utf-8")

        config = load_team_config(child)
        self.assertEqual(config.default_tier, "solo")
        self.assertNotIn("fast", config.model_presets.get("codex", {}).get("balanced", {}).models if "codex" in config.model_presets else {})
        self.assertNotEqual(config.field_origins.get("default_tier"), "user")

    def test_project_root_bounded_by_git_repository(self) -> None:
        (self.workspace / ".agent-team").mkdir()
        (self.workspace / ".agent-team" / "team.toml").write_text("schema_version = 1\n", encoding="utf-8")

        git_repo = self.workspace / "repo"
        git_repo.mkdir()
        subprocess.run(["git", "init", "-q", str(git_repo)], check=True)
        subpkg = git_repo / "packages" / "sub"
        subpkg.mkdir(parents=True)

        # project_root inside git_repo must stay at git_repo, not escape to self.workspace
        self.assertEqual(project_root(subpkg), git_repo.resolve())
        self.assertEqual(project_root(git_repo), git_repo.resolve())

        # When subpkg has its own .agent-team/team.toml, subpkg is the project root
        (subpkg / ".agent-team").mkdir(parents=True)
        (subpkg / ".agent-team" / "team.toml").write_text("schema_version = 1\n", encoding="utf-8")
        self.assertEqual(project_root(subpkg), subpkg.resolve())

    def test_cli_commands_work_in_uninitialized_project(self) -> None:
        project = self.workspace / "cli-project"
        project.mkdir()
        self.write_user("""schema_version = 1
default_tier = "assisted"
default_model_preset = "balanced"
enabled_targets = ["claude"]

[model_presets.claude.balanced.models]
fast = "user-fast"
""")
        with patch("agent_team.cli.project_root", return_value=project):
            # 1. validate
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["validate", "--format", "text"])
            self.assertEqual(exit_code, 0, output.getvalue())

            # 2. doctor
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["doctor", "--format", "text"])
            self.assertEqual(exit_code, 0, output.getvalue())
            self.assertIn("valid configuration at", output.getvalue())

            # 3. models show
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["models", "show", "--format", "table"])
            self.assertEqual(exit_code, 0, output.getvalue())
            self.assertIn("user:model_presets.claude.balanced.models.fast", output.getvalue())

            # 4. run init
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["run", "init", "--slug", "adhoc-run"])
            self.assertEqual(exit_code, 0, output.getvalue())
            self.assertTrue((project / ".agent-team" / "runs" / "adhoc-run" / "run.toml").is_file())

            # 5. generate gitignore
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["generate", "gitignore"])
            self.assertEqual(exit_code, 0, output.getvalue())
            self.assertTrue((project / ".gitignore").is_file())


if __name__ == "__main__":
    unittest.main()
