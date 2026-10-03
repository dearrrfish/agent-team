import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_team.templates import asset_text

SOURCE = str(Path(__file__).parents[1] / "src")


class GlobalCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "project"
        self.home = Path(self.directory.name) / "home"
        self.root.mkdir()
        self.home.mkdir()

    def run_cli(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "agent_team", *args], cwd=cwd or self.root,
            env={**os.environ, "HOME": str(self.home), "PYTHONPATH": SOURCE, "ANTHROPIC_API_KEY": ""},
            text=True, capture_output=True, check=False,
        )

    def test_scopes_help_and_existing_config(self) -> None:
        help_result = self.run_cli("init", "--help")
        self.assertIn("live user defaults", help_result.stdout)
        self.assertEqual(self.run_cli("init", "--scope", "user").returncode, 0)
        config = self.home / ".agent-team" / "team.toml"
        before = config.read_bytes()
        again = self.run_cli("init", "--scope", "user")
        self.assertIn("warning", again.stderr)
        self.assertEqual(config.read_bytes(), before)
        self.assertFalse((self.root / ".agent-team").exists())
        self.assertEqual(self.run_cli("init").returncode, 0)
        self.assertLess(len((self.root / ".agent-team" / "team.toml").read_bytes()), len(before))
        self.assertFalse((self.root / ".gitignore").exists())

    def test_projects_beneath_home_do_not_select_user_config(self) -> None:
        self.assertEqual(self.run_cli("init", "--scope", "user").returncode, 0)
        for use_git in (False, True):
            with self.subTest(git=use_git):
                project = self.home / "codes" / ("git-project" if use_git else "plain-project")
                project.mkdir(parents=True)
                if use_git:
                    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
                initialized = self.run_cli("init", cwd=project)
                self.assertEqual(initialized.returncode, 0, initialized.stderr)
                self.assertTrue((project / ".agent-team/team.toml").is_file())
                generated = self.run_cli("generate", "templates", cwd=project)
                self.assertEqual(generated.returncode, 0, generated.stderr)
                self.assertTrue((project / ".agent-team/templates/prompts/plan.md").is_file())
        self.assertFalse((self.home / ".agent-team/templates").exists())

    def test_project_commands_reject_home_and_user_config_directory(self) -> None:
        self.run_cli("init", "--scope", "user")
        user_file = self.home / ".agent-team/team.toml"
        before = user_file.read_bytes()
        for cwd in (self.home, user_file.parent):
            for args in (("init",), ("generate",), ("run", "init", "--slug", "invalid"),
                         ("install", "--scope", "project", "--target", "codex", "--apply")):
                with self.subTest(cwd=cwd, args=args):
                    result = self.run_cli(*args, cwd=cwd)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("project", result.stderr)
        self.assertEqual(user_file.read_bytes(), before)
        for directory in ("runs", "templates", "backups", ".agent-team"):
            self.assertFalse((user_file.parent / directory).exists())

    def test_complete_install_file_tree_preflight(self) -> None:
        self.run_cli("init")
        for target, destination in (("codex", ".shared"), ("claude", ".shared/coordinator.toml")):
            profile = asset_text("definitions", "targets", f"{target}.toml")
            profile = profile.replace(f'\nagent_destination = ".{target}/agents"',
                                      f'\nagent_destination = "{destination}"')
            (self.root / f"{target}.toml").write_text(profile)
        (self.root / ".agent-team/team.toml").write_text(
            '[target_profiles]\ncodex = "codex.toml"\nclaude = "claude.toml"\n'
        )
        failed = self.run_cli("install", "--target", "codex,claude", "--apply")
        self.assertNotEqual(failed.returncode, 0, failed.stdout)
        self.assertIn("collision", failed.stderr)
        self.assertFalse((self.root / ".shared").exists())
        self.assertFalse((self.root / ".agent-team/install-state.json").exists())

    def test_install_alias_collision_preflight(self) -> None:
        self.run_cli("init")
        alias = self.root / ".codex/agents/coordinator.toml"
        alias.parent.mkdir(parents=True)
        alias.symlink_to("../../.claude/agents/coordinator.md")
        failed = self.run_cli("install", "--target", "codex,claude", "--apply")
        self.assertNotEqual(failed.returncode, 0, failed.stdout)
        self.assertIn("collision", failed.stderr)
        self.assertFalse((self.root / ".claude").exists())
        self.assertEqual(list(alias.parent.iterdir()), [alias])
        self.assertFalse((self.root / ".agent-team/install-state.json").exists())

    def test_install_state_is_reserved_file_in_preflight(self) -> None:
        self.run_cli("init")
        profile = asset_text("definitions", "targets", "codex.toml").replace(
            '\nagent_destination = ".codex/agents"',
            '\nagent_destination = ".agent-team/install-state.json"',
        )
        (self.root / "codex.toml").write_text(profile)
        (self.root / ".agent-team/team.toml").write_text('[target_profiles]\ncodex = "codex.toml"')
        failed = self.run_cli("install", "--target", "codex", "--apply")
        self.assertNotEqual(failed.returncode, 0, failed.stdout)
        self.assertIn("collision", failed.stderr)
        self.assertFalse((self.root / ".agent-team/install-state.json").exists())
        self.assertFalse((self.root / ".agents").exists())

    def test_generate_preserves_custom_sources_matching_native_wildcards(self) -> None:
        self.run_cli("init")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        source = self.root / ".custom/skills/team-plan"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text(asset_text("skills", "team-plan", "SKILL.md"))
        (source / "reference.md").write_text("Authored supporting material")
        profile = self.root / ".custom/agents/coordinator-profile.toml"
        profile.parent.mkdir(parents=True)
        profile.write_text(asset_text("definitions", "targets", "codex.toml"))
        (self.root / ".agent-team/team.toml").write_text(
            'inherit_user_defaults = false\nskill_sources = [".custom/skills"]\n'
            '[target_profiles]\ncodex = ".custom/agents/coordinator-profile.toml"'
        )
        generated = self.run_cli("generate", "gitignore")
        self.assertEqual(generated.returncode, 0, generated.stderr)
        for path in (".custom/skills/team-plan/SKILL.md", ".custom/skills/team-plan/reference.md",
                     ".custom/agents/coordinator-profile.toml"):
            ignored = subprocess.run(["git", "check-ignore", path], cwd=self.root,
                                     capture_output=True, check=False)
            self.assertEqual(ignored.returncode, 1, path)
        native = subprocess.run(["git", "check-ignore", ".agents/skills/team-plan/SKILL.md"],
                                cwd=self.root, capture_output=True, check=False)
        self.assertEqual(native.returncode, 0)
        before = (self.root / ".gitignore").read_bytes()
        self.assertEqual(self.run_cli("generate", "gitignore").returncode, 0)
        self.assertEqual((self.root / ".gitignore").read_bytes(), before)

    def test_user_missing_run_and_targets_rejected_before_writes(self) -> None:
        missing = self.run_cli("install", "--scope", "user", "--target", "codex", "--apply")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("init --scope user", missing.stderr)
        self.run_cli("init", "--scope", "user")
        for target in ("codex,unknown", "codex,codex", "codex,", ""):
            result = self.run_cli("install", "--scope", "user", "--target", target, "--apply")
            self.assertNotEqual(result.returncode, 0, target)
        result = self.run_cli("install", "--scope", "user", "--target", "codex", "--run", "x")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.home / ".codex").exists())

    def test_multi_target_preflight_and_preview(self) -> None:
        self.run_cli("init")
        conflict = self.root / ".claude" / "agents" / "coordinator.md"
        conflict.parent.mkdir(parents=True)
        conflict.write_text("handwritten")
        failed = self.run_cli("install", "--target", "codex,claude", "--apply")
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse((self.root / ".codex").exists())
        preview = self.run_cli("install", "--target", "codex")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertFalse((self.root / ".codex").exists())

    def test_user_backup_project_only_and_no_context_rejected(self) -> None:
        self.run_cli("init", "--scope", "user")
        self.run_cli("init")
        conflict = self.home / ".codex" / "agents" / "coordinator.toml"
        conflict.parent.mkdir(parents=True)
        conflict.write_text("handwritten")
        failed = self.run_cli("install", "--scope", "user", "--target", "codex", "--apply", "--force", cwd=self.home)
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(conflict.read_text(), "handwritten")
        applied = self.run_cli("install", "--scope", "user", "--target", "codex,claude,antigravity", "--apply", "--force")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertTrue(list((self.root / ".agent-team" / "backups").rglob("coordinator.toml")))
        self.assertFalse((self.home / ".agent-team" / "backups").exists())

    def test_generate_selectors_and_wildcards(self) -> None:
        invalid = self.run_cli("generate", "templates,wrong")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertFalse((self.root / ".agent-team").exists())
        self.assertEqual(self.run_cli("generate", "gitignore").returncode, 0)
        self.assertFalse((self.root / ".agent-team").exists())
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        for path in (".codex/skills/team-plan/SKILL.md", ".claude/agents/explorer.md", ".agents/agents/ops/agent.md"):
            result = subprocess.run(["git", "check-ignore", path], cwd=self.root, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, path)
        self.assertNotEqual(subprocess.run(["git", "check-ignore", ".agents/definitions/roles/ops/role.toml"], cwd=self.root, capture_output=True, check=False).returncode, 0)
        self.assertEqual(self.run_cli("generate", "gitignore,", "templates").returncode, 0)
        self.assertTrue((self.root / ".agent-team" / "templates" / "prompts" / "plan.md").is_file())

    def test_model_table_has_sources(self) -> None:
        self.run_cli("init")
        result = self.run_cli("models", "show", "--target", "codex", "--format", "table")
        self.assertEqual(result.returncode, 0, result.stderr)
        for label in ("Target", "Preset", "Role", "Model source", "coordinator"):
            self.assertIn(label, result.stdout)
        fetched = self.run_cli("models", "fetch", "--target", "claude", "--format", "table")
        self.assertIn("profile effort levels", fetched.stdout)
