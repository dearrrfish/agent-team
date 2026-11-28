import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_team.config import (
    DEFAULT_TEAM_TOML,
    effective_default_preset,
    load_builtin_roles,
    load_target_profile,
    load_team_config,
    parse_role,
    parse_target_profile,
    parse_team_config,
    project_root,
    resolve_target_profile,
    resolve_tier,
)
from agent_team.diagnostics import ValidationFailure
from agent_team.models import PRESETS, TARGETS, DispatchPreset, TargetPreset
from agent_team.templates import asset_text


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.home_dir.cleanup)
        self.home_patch = patch("pathlib.Path.home", return_value=Path(self.home_dir.name))
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)

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

    def test_non_reviewer_role_rejects_review_cycle_report(self) -> None:
        data = tomllib.loads(asset_text("definitions", "roles", "explorer", "role.toml"))
        data["id"] = "analyst"
        data["report_kind"] = "review-cycle"
        with self.assertRaises(ValidationFailure) as context:
            parse_role(data, "# Instructions\n", "roles.analyst")
        self.assertTrue(any(
            item.path == "roles.analyst.report_kind" and item.code == "invariant"
            for item in context.exception.diagnostics
        ))

    def test_builtin_target_profiles_cover_all_presets(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            config = load_team_config(root)
            codex = load_target_profile("codex", config.target_profiles["codex"], root)
            claude = load_target_profile("claude", config.target_profiles["claude"], root)
            antigravity = load_target_profile("antigravity", config.target_profiles["antigravity"], root)
            self.assertEqual(codex.presets["balanced"].models["deep"], "gpt-6-sol")
            self.assertEqual(codex.presets["quality"].models["deep"], "gpt-6-astra")
            self.assertEqual(claude.presets["quality"].models["deep"], "opus")
            self.assertEqual(claude.presets["quality"].coordinator_model, "opus")
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

    def test_model_preset_overrides_merge_leaves_over_the_selected_profile(self) -> None:
        config_text = DEFAULT_TEAM_TOML + '''

[model_presets.codex.balanced]
coordinator_model = "project-coordinator"
coordinator_effort = "xhigh"
[model_presets.codex.balanced.models]
fast = "project-fast"
[model_presets.codex.balanced.effort]
low = "high"
'''
        with self._project() as directory:
            root = Path(directory)
            (root / ".agent-team" / "team.toml").write_text(config_text, encoding="utf-8")
            config = load_team_config(root)
            profile = resolve_target_profile(config, "codex", root)
            preset = profile.presets["balanced"]
            self.assertEqual(preset.coordinator_model, "project-coordinator")
            self.assertEqual(preset.coordinator_effort, "xhigh")
            self.assertEqual(preset.models["fast"], "project-fast")
            self.assertEqual(preset.models["deep"], "gpt-6-sol")
            self.assertEqual(preset.effort["low"], "high")
            self.assertEqual(preset.effort["high"], "high")

    def test_model_preset_overrides_follow_replaced_target_profile(self) -> None:
        config_text = DEFAULT_TEAM_TOML.replace(
            'codex = "builtin:codex"', 'codex = "definitions/codex.toml"'
        ) + '''

[model_presets.codex.balanced.models]
deep = "project-deep"
'''
        with self._project() as directory:
            root = Path(directory)
            definitions = root / "definitions"
            definitions.mkdir()
            profile_text = asset_text("definitions", "targets", "codex.toml").replace(
                'coordinator_model = "gpt-6-sol"',
                'coordinator_model = "profile-coordinator"',
                1,
            )
            (definitions / "codex.toml").write_text(profile_text, encoding="utf-8")
            (root / ".agent-team" / "team.toml").write_text(config_text, encoding="utf-8")
            config = load_team_config(root)
            preset = resolve_target_profile(config, "codex", root).presets["balanced"]
            self.assertEqual(preset.coordinator_model, "profile-coordinator")
            self.assertEqual(preset.models["deep"], "project-deep")

    def test_model_preset_override_rejects_unknown_keys_and_empty_models(self) -> None:
        data = tomllib.loads(DEFAULT_TEAM_TOML)
        data["model_presets"] = {
            "codex": {"balanced": {"models": {"unexpected": "model"}}},
            "claude": {"quality": {"coordinator_model": ""}},
            "antigravity": {"balanced": {"coordinator_model": "pro\n---\nInjected instructions"}},
        }
        with self.assertRaises(ValidationFailure) as context:
            parse_team_config(data, Path("/tmp/project"))
        paths = {item.path for item in context.exception.diagnostics}
        self.assertIn("model_presets.codex.balanced.models.unexpected", paths)
        self.assertIn("model_presets.claude.quality.coordinator_model", paths)
        self.assertIn("model_presets.antigravity.balanced.coordinator_model", paths)

    def test_model_preset_override_rejects_unsupported_effort(self) -> None:
        config_text = DEFAULT_TEAM_TOML + '''

[model_presets.claude.balanced]
coordinator_effort = "ultra"
[model_presets.antigravity.balanced.effort]
low = "low"
'''
        with self._project() as directory:
            root = Path(directory)
            (root / ".agent-team" / "team.toml").write_text(config_text, encoding="utf-8")
            config = load_team_config(root)
            with self.assertRaises(ValidationFailure) as claude_context:
                resolve_target_profile(config, "claude", root)
            self.assertTrue(any(
                item.path == "model_presets.claude.balanced.coordinator_effort" and item.code == "enum"
                for item in claude_context.exception.diagnostics
            ))
            with self.assertRaises(ValidationFailure) as antigravity_context:
                resolve_target_profile(config, "antigravity", root)
            self.assertTrue(any(
                item.path == "model_presets.antigravity.balanced.effort.low" and item.code == "invariant"
                for item in antigravity_context.exception.diagnostics
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

    def _write_team(self, root: Path, extra: str, *, profile_text: str | None = None) -> None:
        team = DEFAULT_TEAM_TOML
        if profile_text is not None:
            (root / "codex.toml").write_text(profile_text, encoding="utf-8")
            team = team.replace('codex = "builtin:codex"', 'codex = "codex.toml"')
        (root / ".agent-team" / "team.toml").write_text(team + extra, encoding="utf-8")

    def test_target_profile_custom_preset_expands_template_defaults(self) -> None:
        data = tomllib.loads(asset_text("definitions", "targets", "codex.toml"))
        data["presets"]["turbo"] = {"template": "quality", "models": {"deep": "turbo-deep"}}
        profile = parse_target_profile(data, "custom.codex")
        turbo = profile.presets["turbo"]
        self.assertEqual(turbo.coordinator_model, "gpt-6-astra")
        self.assertEqual(turbo.coordinator_effort, "medium")
        self.assertEqual(
            dict(turbo.models),
            {"fast": "gpt-5.6-terra", "balanced": "gpt-6-sol", "deep": "turbo-deep"},
        )
        self.assertEqual(dict(turbo.effort), {"low": "medium", "medium": "high", "high": "xhigh"})
        self.assertEqual(list(profile.presets), [*PRESETS, "turbo"])

    def test_target_profile_custom_preset_rejects_template_chain(self) -> None:
        data = tomllib.loads(asset_text("definitions", "targets", "codex.toml"))
        data["presets"]["alpha"] = {"template": "quality"}
        data["presets"]["beta"] = {"template": "alpha"}
        with self.assertRaises(ValidationFailure) as context:
            parse_target_profile(data, "custom.codex")
        self.assertTrue(any(
            item.path == "custom.codex.presets.beta.template" and item.code == "enum"
            for item in context.exception.diagnostics
        ))

    def test_target_profile_custom_preset_requires_template_base(self) -> None:
        data = tomllib.loads(asset_text("definitions", "targets", "codex.toml"))
        data["presets"]["turbo"] = {"template": "nonexistent"}
        with self.assertRaises(ValidationFailure) as context:
            parse_target_profile(data, "custom.codex")
        self.assertTrue(any(
            item.path == "custom.codex.presets.turbo.template" and item.code == "enum"
            for item in context.exception.diagnostics
        ))

    def test_target_profile_custom_preset_requires_completeness_after_expansion(self) -> None:
        data = tomllib.loads(asset_text("definitions", "targets", "codex.toml"))
        data["presets"]["partial"] = {"models": {"fast": "only-fast"}}
        with self.assertRaises(ValidationFailure) as context:
            parse_target_profile(data, "custom.codex")
        paths = {
            item.path for item in context.exception.diagnostics if item.code == "required"
        }
        self.assertIn("custom.codex.presets.partial.coordinator_model", paths)
        self.assertIn("custom.codex.presets.partial.models", paths)

    def test_target_profile_custom_preset_rejects_invalid_name(self) -> None:
        data = tomllib.loads(asset_text("definitions", "targets", "codex.toml"))
        data["presets"]["Bad_Name"] = {"template": "quality"}
        with self.assertRaises(ValidationFailure) as context:
            parse_target_profile(data, "custom.codex")
        self.assertTrue(any(
            item.path == "custom.codex.presets.Bad_Name" and item.code == "format"
            for item in context.exception.diagnostics
        ))

    def test_target_profile_template_drops_inherited_effort_without_effort_support(self) -> None:
        data = tomllib.loads(asset_text("definitions", "targets", "antigravity.toml"))
        data["presets"]["pro-fast"] = {"template": "quality"}
        profile = parse_target_profile(data, "custom.antigravity")
        pro_fast = profile.presets["pro-fast"]
        self.assertEqual(dict(pro_fast.effort), {})
        self.assertIsNone(pro_fast.coordinator_effort)
        self.assertEqual(pro_fast.models["deep"], "pro")

        data["presets"]["pro-fast"].update(effort={"low": "low"}, coordinator_effort="high")
        with self.assertRaises(ValidationFailure) as context:
            parse_target_profile(data, "custom.antigravity")
        self.assertEqual({item.path for item in context.exception.diagnostics if item.code == "enum"}, {
            "custom.antigravity.presets.pro-fast.effort.low",
            "custom.antigravity.presets.pro-fast.coordinator_effort",
        })

    def test_custom_preset_accepts_sparse_team_overrides(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            self._write_team(
                root,
                '\n[model_presets.codex.turbo.models]\ndeep = "team-deep"\n',
                profile_text=(
                    asset_text("definitions", "targets", "codex.toml")
                    + '\n[presets.turbo]\ntemplate = "quality"\n'
                ),
            )
            config = load_team_config(root)
            turbo = resolve_target_profile(config, "codex", root).presets["turbo"]
            self.assertEqual(turbo.coordinator_model, "gpt-6-astra")
            self.assertEqual(turbo.models["fast"], "gpt-5.6-terra")
            self.assertEqual(turbo.models["deep"], "team-deep")

    def test_model_preset_override_of_undefined_preset_reports_diagnostic(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            self._write_team(
                root, '\n[model_presets.codex.ghost]\ncoordinator_model = "ghost-model"\n'
            )
            config = load_team_config(root)
            with self.assertRaises(ValidationFailure) as context:
                resolve_target_profile(config, "codex", root)
            self.assertTrue(any(
                item.path == "model_presets.codex.ghost" and item.code == "enum"
                for item in context.exception.diagnostics
            ))

    def test_model_presets_can_define_new_preset_from_builtin_template(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            self._write_team(root, '''
[model_presets.codex.quick]
template = "economy"
[model_presets.codex.quick.models]
deep = "quick-deep"
''')
            config = load_team_config(root)
            quick = resolve_target_profile(config, "codex", root).presets["quick"]
            self.assertEqual(quick.coordinator_model, "gpt-5.6-terra")
            self.assertEqual(quick.models["fast"], "gpt-6-luna")
            self.assertEqual(quick.models["deep"], "quick-deep")
            self.assertEqual(dict(quick.effort), {"low": "low", "medium": "medium", "high": "medium"})

    def test_model_preset_template_rejected_when_profile_defines_preset(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            self._write_team(root, '\n[model_presets.codex.balanced]\ntemplate = "quality"\n')
            config = load_team_config(root)
            with self.assertRaises(ValidationFailure) as context:
                resolve_target_profile(config, "codex", root)
            self.assertTrue(any(
                item.path == "model_presets.codex.balanced.template" and item.code == "invariant"
                for item in context.exception.diagnostics
            ))

    def test_model_preset_template_must_name_builtin_preset(self) -> None:
        data = tomllib.loads(DEFAULT_TEAM_TOML)
        data["model_presets"] = {"codex": {"x": {"template": "turbo"}}}
        with self.assertRaises(ValidationFailure) as context:
            parse_team_config(data, Path("/tmp/project"))
        self.assertTrue(any(
            item.path == "model_presets.codex.x.template" and item.code == "enum"
            for item in context.exception.diagnostics
        ))

    def test_default_model_preset_accepts_custom_name_at_parse_time(self) -> None:
        data = tomllib.loads(DEFAULT_TEAM_TOML)
        data["default_model_preset"] = "turbo"
        config = parse_team_config(data, Path("/tmp/project"))
        self.assertEqual(config.default_model_preset, "turbo")

    def test_default_model_preset_rejects_malformed_name(self) -> None:
        data = tomllib.loads(DEFAULT_TEAM_TOML)
        data["default_model_preset"] = "Turbo!"
        with self.assertRaises(ValidationFailure) as context:
            parse_team_config(data, Path("/tmp/project"))
        self.assertTrue(any(
            item.path == "default_model_preset" and item.code == "format"
            for item in context.exception.diagnostics
        ))

    def _scoped_custom_default(self, root: Path, enabled: str) -> None:
        team = DEFAULT_TEAM_TOML.replace(
            'default_model_preset = "balanced"',
            f'default_model_preset = "turbo"\nenabled_targets = [{enabled}]',
        )
        (root / ".agent-team" / "team.toml").write_text(
            team + '\n[model_presets.codex.turbo]\ntemplate = "quality"\n', encoding="utf-8"
        )

    def test_default_model_preset_must_exist_in_enabled_target_profiles(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            self._scoped_custom_default(root, '"codex", "claude"')
            config = load_team_config(root)
            self.assertIn("turbo", resolve_target_profile(config, "codex", root).presets)
            with self.assertRaises(ValidationFailure) as context:
                resolve_target_profile(config, "claude", root, validate_default=True)
            self.assertTrue(any(
                item.path == "default_model_preset" and item.code == "enum"
                for item in context.exception.diagnostics
            ))

    def test_default_model_preset_ignored_for_disabled_targets(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            self._scoped_custom_default(root, '"codex"')
            config = load_team_config(root)
            self.assertEqual(config.enabled_targets, ("codex",))
            for target in ("claude", "pi"):
                with self.subTest(target=target):
                    profile = resolve_target_profile(config, target, root, validate_default=True)
                    self.assertEqual(set(profile.presets), set(PRESETS))

    def test_per_target_default_preset_is_recorded(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            self._write_team(root, '\n[model_presets.codex]\ndefault_preset = "quality"\n')
            config = load_team_config(root)
            self.assertEqual(config.target_default_presets["codex"], "quality")
            self.assertNotIn("default_preset", config.model_presets.get("codex", {}))
            self.assertEqual(config.field_origins["model_presets.codex.default_preset"], "project")
            self.assertEqual(effective_default_preset(config, "codex"), "quality")
            self.assertEqual(effective_default_preset(config, "claude"), "balanced")

    def test_per_target_default_preset_must_exist_in_its_profile(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            self._write_team(root, '\n[model_presets.codex]\ndefault_preset = "ghost"\n')
            config = load_team_config(root)
            with self.assertRaises(ValidationFailure) as context:
                resolve_target_profile(config, "codex", root, validate_default=True)
            self.assertTrue(any(
                item.path == "model_presets.codex.default_preset" and item.code == "enum"
                for item in context.exception.diagnostics
            ))

    def test_builtin_target_profiles_parse_identically(self) -> None:
        expected_quality = {
            "codex": ("gpt-6-astra", "medium", "gpt-5.6-terra", "gpt-6-sol", "gpt-6-astra"),
            "claude": ("opus", "high", "sonnet", "sonnet", "opus"),
            "antigravity": ("pro", None, "flash", "pro", "pro"),
            "pi": ("openai/gpt-5.4", "medium", "openai/gpt-5.4-mini", "openai/gpt-5.4", "openai/gpt-5.4"),
        }
        for target in TARGETS:
            with self.subTest(target=target):
                profile = load_target_profile(target, f"builtin:{target}", Path(".").resolve())
                self.assertEqual(list(profile.presets), list(PRESETS))
                declared = tomllib.loads(asset_text("definitions", "targets", f"{target}.toml"))
                for preset_name in PRESETS:
                    literal = declared["presets"][preset_name]
                    dispatch = (
                        DispatchPreset(**literal["dispatch"])
                        if "dispatch" in literal else None
                    )
                    self.assertEqual(profile.presets[preset_name], TargetPreset(
                        coordinator_model=literal["coordinator_model"],
                        coordinator_effort=literal.get("coordinator_effort"),
                        models=literal["models"],
                        effort=literal.get("effort", {}),
                        dispatch=dispatch,
                    ))
                quality = profile.presets["quality"]
                self.assertEqual(
                    (
                        quality.coordinator_model,
                        quality.coordinator_effort,
                        quality.models["fast"],
                        quality.models["balanced"],
                        quality.models["deep"],
                    ),
                    expected_quality[target],
                )
        codex = load_target_profile("codex", "builtin:codex", Path(".").resolve())
        self.assertEqual(codex.presets["balanced"].coordinator_effort, "medium")
        self.assertEqual(codex.presets["balanced"].models["deep"], "gpt-6-sol")
        antigravity = load_target_profile("antigravity", "builtin:antigravity", Path(".").resolve())
        self.assertFalse(antigravity.supports_effort)
        self.assertEqual(antigravity.effort_levels, ())
        self.assertTrue(antigravity.effective_supports_dispatch_effort)
        self.assertEqual(antigravity.dispatch_effort_levels, ("low", "medium", "high", "xhigh", "max"))
        self.assertEqual(
            antigravity.presets["balanced"].dispatch,
            DispatchPreset(
                coordinator_model="gemini-4-neon",
                coordinator_effort="medium",
                models={
                    "fast": "gemini-3.8-flash",
                    "balanced": "gemini-4-hydrogen",
                    "deep": "gemini-4-neon",
                },
                effort={"low": "low", "medium": "medium", "high": "high"},
            ),
        )

    def test_antigravity_dispatch_sparse_override_and_template_inheritance(self) -> None:
        config_text = DEFAULT_TEAM_TOML + '''

[model_presets.antigravity.balanced.dispatch]
coordinator_model = "gemini-4-carbon"
coordinator_effort = "low"
[model_presets.antigravity.balanced.dispatch.models]
fast = "gemini-4-hydrogen"
[model_presets.antigravity.balanced.dispatch.effort]
high = "xhigh"

[model_presets.antigravity.custom-neon]
template = "quality"
[model_presets.antigravity.custom-neon.dispatch.models]
fast = "gemini-3.8-flash"
'''
        with self._project() as directory:
            root = Path(directory)
            (root / ".agent-team" / "team.toml").write_text(config_text, encoding="utf-8")
            config = load_team_config(root)
            profile = resolve_target_profile(config, "antigravity", root)
            balanced = profile.presets["balanced"]
            self.assertEqual(balanced.coordinator_model, "pro")
            self.assertEqual(balanced.models, {"fast": "flash", "balanced": "pro", "deep": "pro"})
            self.assertEqual(balanced.dispatch, DispatchPreset(
                coordinator_model="gemini-4-carbon",
                coordinator_effort="low",
                models={"fast": "gemini-4-hydrogen", "balanced": "gemini-4-hydrogen", "deep": "gemini-4-neon"},
                effort={"low": "low", "medium": "medium", "high": "xhigh"},
            ))
            custom = profile.presets["custom-neon"]
            self.assertEqual(custom.models["fast"], "flash")
            self.assertIsNone(custom.coordinator_effort)
            self.assertEqual(custom.dispatch, DispatchPreset(
                coordinator_model="gemini-4-neon",
                coordinator_effort="high",
                models={"fast": "gemini-3.8-flash", "balanced": "gemini-4-neon", "deep": "gemini-4-neon"},
                effort={"low": "medium", "medium": "high", "high": "xhigh"},
            ))

    def test_antigravity_dispatch_validation_errors_and_legacy_profile(self) -> None:
        bad_team = tomllib.loads(DEFAULT_TEAM_TOML)
        bad_team["model_presets"] = {
            "antigravity": {
                "balanced": {
                    "dispatch": {
                        "unknown_key": "x",
                        "coordinator_model": "   ",
                    },
                },
            },
        }
        with self.assertRaises(ValidationFailure) as team_ctx:
            parse_team_config(bad_team, Path("/tmp/project"))
        paths = {item.path for item in team_ctx.exception.diagnostics}
        self.assertIn("model_presets.antigravity.balanced.dispatch.unknown_key", paths)
        self.assertIn("model_presets.antigravity.balanced.dispatch.coordinator_model", paths)

        with self._project() as directory:
            root = Path(directory)
            (root / ".agent-team" / "team.toml").write_text(
                DEFAULT_TEAM_TOML
                + '\n[model_presets.antigravity.balanced.dispatch]\ncoordinator_effort = "ultra"\n',
                encoding="utf-8",
            )
            config = load_team_config(root)
            with self.assertRaises(ValidationFailure) as enum_ctx:
                resolve_target_profile(config, "antigravity", root)
            self.assertTrue(any(
                item.path == "model_presets.antigravity.balanced.dispatch.coordinator_effort"
                and item.code == "enum"
                for item in enum_ctx.exception.diagnostics
            ))

            legacy_profile = '''
schema_version = 1
id = "antigravity"
adapter = "antigravity"
agent_destination = ".agents/agents"
skill_destination = ".agents/skills"
user_agent_destination = ".gemini/config/agents"
user_skill_destination = ".gemini/antigravity-cli/skills"
models_without_effort = []

[features]
supports_effort = false
effort_levels = []
supports_worktree_isolation = true
team_runtime = "subagents"

[presets.economy]
coordinator_model = "flash"
[presets.economy.models]
fast = "flash"
balanced = "flash"
deep = "pro"

[presets.balanced]
coordinator_model = "pro"
[presets.balanced.models]
fast = "flash"
balanced = "pro"
deep = "pro"

[presets.quality]
coordinator_model = "pro"
[presets.quality.models]
fast = "flash"
balanced = "pro"
deep = "pro"
'''
            (root / "legacy-agy.toml").write_text(legacy_profile, encoding="utf-8")
            (root / ".agent-team" / "team.toml").write_text(
                DEFAULT_TEAM_TOML.replace(
                    'antigravity = "builtin:antigravity"',
                    'antigravity = "legacy-agy.toml"',
                )
                + '\n[model_presets.antigravity.balanced.dispatch.effort]\nlow = "low"\n',
                encoding="utf-8",
            )
            legacy_config = load_team_config(root)
            with self.assertRaises(ValidationFailure) as inv_ctx:
                resolve_target_profile(legacy_config, "antigravity", root)
            self.assertTrue(any(
                item.path == "model_presets.antigravity.balanced.dispatch.effort.low"
                and item.code == "invariant"
                for item in inv_ctx.exception.diagnostics
            ))


if __name__ == "__main__":
    unittest.main()
