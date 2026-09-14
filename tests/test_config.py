import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

from agent_team.config import (
    DEFAULT_TEAM_TOML,
    load_builtin_roles,
    load_target_profile,
    load_team_config,
    parse_target_profile,
    parse_team_config,
    project_root,
    resolve_tier,
)
from agent_team.diagnostics import ValidationFailure
from agent_team.templates import asset_text


class ConfigTests(unittest.TestCase):
    def _project(self) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / ".agent-team").mkdir()
        (root / ".agent-team" / "team.toml").write_text(DEFAULT_TEAM_TOML, encoding="utf-8")
        return temporary

    def test_default_config_is_strict_and_complete(self) -> None:
        with self._project() as directory:
            config = load_team_config(Path(directory))
            self.assertEqual(config.default_tier, "adaptive")
            self.assertEqual(config.tiers["team"].max_workers, 4)
            self.assertTrue(config.tiers["team"].independent_review)
            self.assertFalse(config.install.modify_native_settings)

    def test_unknown_key_is_rejected_with_dotted_path(self) -> None:
        data = tomllib.loads(DEFAULT_TEAM_TOML)
        data["install"]["surprise"] = True
        with self.assertRaises(ValidationFailure) as context:
            parse_team_config(data, Path("/tmp/project"))
        self.assertIn("install.surprise", str(context.exception))

    def test_tier_bounds_and_path_containment_are_enforced(self) -> None:
        data = tomllib.loads(DEFAULT_TEAM_TOML)
        data["tiers"]["assisted"]["max_workers"] = 3
        data["workflow"]["run_root"] = "../elsewhere"
        with self.assertRaises(ValidationFailure) as context:
            parse_team_config(data, Path("/tmp/project"))
        paths = {item.path for item in context.exception.diagnostics}
        self.assertIn("tiers.assisted.max_workers", paths)
        self.assertIn("workflow.run_root", paths)

    def test_existing_run_root_must_be_a_directory(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            (root / "run-state").write_text("not a directory\n", encoding="utf-8")
            config_text = DEFAULT_TEAM_TOML.replace(
                'run_root = ".agent-team/runs"', 'run_root = "run-state"'
            )
            (root / ".agent-team" / "team.toml").write_text(config_text, encoding="utf-8")
            with self.assertRaises(ValidationFailure) as context:
                load_team_config(root)
            self.assertTrue(any(
                item.path == "workflow.run_root" and item.code == "path"
                for item in context.exception.diagnostics
            ))

    def test_assisted_and_team_require_durable_artifacts(self) -> None:
        data = tomllib.loads(DEFAULT_TEAM_TOML)
        data["tiers"]["assisted"]["durable_artifacts"] = False
        data["tiers"]["team"]["durable_artifacts"] = False
        with self.assertRaises(ValidationFailure) as context:
            parse_team_config(data, Path("/tmp/project"))
        paths = {item.path for item in context.exception.diagnostics}
        self.assertIn("tiers.assisted.durable_artifacts", paths)
        self.assertIn("tiers.team.durable_artifacts", paths)

    def test_builtin_roles_obey_write_and_review_contracts(self) -> None:
        roles = {role.role_id: role for role in load_builtin_roles()}
        self.assertEqual(set(roles), {"coordinator", "explorer", "design-agent", "implementer", "ops", "reviewer"})
        self.assertEqual(roles["explorer"].write_policy, "deny")
        self.assertNotIn("filesystem.write", roles["reviewer"].capabilities)
        self.assertEqual(roles["reviewer"].report_kind, "review-cycle")
        self.assertTrue(roles["coordinator"].delegation)
        self.assertFalse(any(
            role.delegation for role_id, role in roles.items() if role_id != "coordinator"
        ))

    def test_builtin_target_profiles_cover_all_presets(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            config = load_team_config(root)
            codex = load_target_profile("codex", config.target_profiles["codex"], root)
            claude = load_target_profile("claude", config.target_profiles["claude"], root)
            antigravity = load_target_profile("antigravity", config.target_profiles["antigravity"], root)
            self.assertEqual(codex.presets["balanced"].models["deep"], "gpt-5.6-sol")
            self.assertEqual(codex.presets["quality"].models["deep"], "gpt-6-astra")
            self.assertEqual(codex.presets["balanced"].coordinator_effort, "medium")
            self.assertIn("ultra", codex.effort_levels)
            self.assertIn("haiku", claude.models_without_effort)
            self.assertNotIn("ultra", claude.effort_levels)
            self.assertFalse(antigravity.supports_effort)
            self.assertTrue(antigravity.supports_worktree_isolation)
            self.assertEqual(antigravity.user_agent_destination, ".gemini/config/agents")

    def test_target_profiles_accept_ultra_native_effort(self) -> None:
        data = tomllib.loads(asset_text("definitions", "targets", "codex.toml"))
        data["presets"]["quality"]["effort"]["high"] = "ultra"
        profile = parse_target_profile(data, "custom.codex")
        self.assertEqual(profile.presets["quality"].effort["high"], "ultra")

    def test_target_profile_rejects_unsupported_target_effort(self) -> None:
        data = tomllib.loads(asset_text("definitions", "targets", "claude.toml"))
        data["presets"]["quality"]["effort"]["high"] = "ultra"
        with self.assertRaises(ValidationFailure) as context:
            parse_target_profile(data, "custom.claude")
        self.assertTrue(any(
            item.path.endswith(".presets.quality.effort.high") and item.code == "enum"
            for item in context.exception.diagnostics
        ))

    def test_project_root_falls_back_to_git_toplevel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            nested = root / "nested" / "directory"
            nested.mkdir(parents=True)
            self.assertEqual(project_root(nested), root.resolve())

    def test_adaptive_tier_counts_files_relative_to_a_worktree_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".worktrees" / "feature"
            (root / ".agent-team").mkdir(parents=True)
            (root / ".agent-team" / "team.toml").write_text(DEFAULT_TEAM_TOML, encoding="utf-8")
            for index in range(26):
                (root / f"source-{index}.py").write_text("pass\n", encoding="utf-8")
            config = load_team_config(root)
            self.assertEqual(resolve_tier(config, root, None), "assisted")


if __name__ == "__main__":
    unittest.main()
