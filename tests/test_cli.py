import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from agent_team import cli
from agent_team.catalog import CatalogResult
from agent_team.models import ROLE_IDS
from agent_team.templates import asset_text
from agent_team.version import __base_version__, get_version
from tests.test_customization import CUSTOM_ROLE

SOURCE = str(Path(__file__).parents[1] / "src")

CUSTOM_PRESET_NAME = "spark"
CUSTOM_PRESET_COORDINATOR = "spark-coordinator"


def _builtin_preset(target: str, preset: str) -> dict:
    return tomllib.loads(asset_text("definitions", "targets", f"{target}.toml"))["presets"][preset]


def _append_team_config(root: Path, snippet: str) -> None:
    config = root / ".agent-team" / "team.toml"
    config.write_text(config.read_text(encoding="utf-8") + "\n" + snippet.strip() + "\n", encoding="utf-8")


def _define_custom_preset(root: Path, target: str = "codex", name: str = CUSTOM_PRESET_NAME) -> None:
    _append_team_config(
        root,
        f"[model_presets.{target}.{name}]\n"
        f'template = "economy"\n'
        f'coordinator_model = "{CUSTOM_PRESET_COORDINATOR}"',
    )


def _set_default_preset(root: Path, target: str, name: str) -> None:
    _append_team_config(root, f'[model_presets.{target}]\ndefault_preset = "{name}"')


class CliTests(unittest.TestCase):
    def _run(
        self,
        root: Path,
        *arguments: str,
        environment_overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = SOURCE
        environment["HOME"] = str(root / "isolated-home")
        environment.update(environment_overrides or {})
        return subprocess.run(
            [sys.executable, "-m", "agent_team", *arguments],
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_dsh_compatibility_updates_and_restores_managed_files(self) -> None:
        for scope in ("project", "user"):
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                scope_root = root if scope == "project" else root / "isolated-home"
                config = scope_root / ".agent-team/team.toml"
                session = {"DSH_SHELL": "", "DSH_SESSION_ID": ""}
                result = self._run(root, "init", "--scope", scope)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = ("install", "--scope", scope, "--target", "codex")
                result = self._run(root, *args, "--apply", environment_overrides=session)
                self.assertEqual(result.returncode, 0, result.stderr)
                review = scope_root / ".agents/skills/team-review/SKILL.md"
                reference = review.parent / "references/agent-team-workflow.md"
                agent = scope_root / ".codex/agents/reviewer.toml"
                standard_config = config.read_text(encoding="utf-8")
                standard_skill = review.read_bytes()
                standard_agent = agent.read_bytes()
                self.assertFalse(reference.exists())
                config.write_text(standard_config + "\n[compatibility]\ndsh = true\n", encoding="utf-8")
                preview = self._run(root, *args, environment_overrides=session)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                self.assertIn("update    .agents/skills/team-review/SKILL.md", preview.stdout)
                self.assertIn("update    .codex/agents/reviewer.toml", preview.stdout)
                self.assertEqual(review.read_bytes(), standard_skill)
                self.assertEqual(agent.read_bytes(), standard_agent)
                result = self._run(root, *args, "--apply", environment_overrides=session)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(b"DeepSeek Harness", review.read_bytes())
                self.assertIn(b"DeepSeek Harness compatibility", agent.read_bytes())
                self.assertIn(b"agent-team run prepare-review", reference.read_bytes())
                self.assertNotIn(b"DSH", reference.read_bytes())
                config.write_text(standard_config + "\n[compatibility]\ndsh = false\n", encoding="utf-8")
                result = self._run(root, *args, "--apply", environment_overrides=session)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(review.read_bytes(), standard_skill)
                self.assertEqual(agent.read_bytes(), standard_agent)

    def test_dsh_scaffold_is_explicit_and_preserves_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = ("dsh", "scaffold", "--output", "bundle")
            result = self._run(root, *args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(root.iterdir()), [root / "bundle"])
            bundle = root / "bundle"
            manifest = json.loads((bundle / "package.json").read_text(encoding="utf-8"))
            patch_path = bundle / manifest["dsh"]["bundle"]["patch"]
            patch_text = patch_path.read_text(encoding="utf-8")
            self.assertEqual(
                [line.strip() for line in patch_text.splitlines() if line.startswith("        id: ")],
                [f"id: agent-team-{role}" for role in ROLE_IDS],
            )
            self.assertEqual(
                [line.strip() for line in patch_text.splitlines() if line.strip().startswith("- agent-team-")],
                [f"- agent-team-{role}" for role in ROLE_IDS if role != "coordinator"],
            )
            self.assertNotIn("subagent_fork", patch_text)
            self.assertFalse((bundle / "spawn-binding.patch.yml").exists())
            for preset_tool in (
                "'@deepseek-ai/dsh-skill-filesystem'",
                "'@deepseek-ai/dsh-tool-skill'",
                "'@deepseek-ai/dsh-tool-fs'",
                "'@deepseek-ai/dsh-tool-bash'",
            ):
                self.assertIn(preset_tool, patch_text)
            self.assertEqual(self._run(root, *args).returncode, 0)
            patch_path.write_text("custom patch\n", encoding="utf-8")
            result = self._run(root, *args)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(patch_path.read_text(encoding="utf-8"), "custom patch\n")

    def test_fresh_project_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
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
            self._run(root, "init", "--scope", "project")
            config = root / ".agent-team" / "team.toml"
            config.write_text(config.read_text(encoding="utf-8").replace("max_workers = 2", "max_workers = 8"), encoding="utf-8")
            result = self._run(root, "validate", "--format", "json")
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertTrue(any(item["path"] == "tiers.assisted.max_workers" for item in payload["diagnostics"]))

    def test_models_show_reports_effective_routing_as_versioned_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            config = root / ".agent-team" / "team.toml"
            config.write_text(
                config.read_text(encoding="utf-8")
                + '\n[model_presets.codex.balanced]\ncoordinator_model = "project-coordinator"\n'
                + '[model_presets.codex.balanced.effort]\nmedium = "high"\n',
                encoding="utf-8",
            )
            result = self._run(root, "models", "show", "--target", "codex", "--format", "json")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema_version"], 1)
            target = payload["targets"][0]
            self.assertEqual(target["target"], "codex")
            coordinator = next(item for item in target["roles"] if item["role_id"] == "coordinator")
            explorer = next(item for item in target["roles"] if item["role_id"] == "explorer")
            self.assertEqual(coordinator["native_model"], "project-coordinator")
            self.assertEqual(coordinator["model_source"], "model_presets.codex.balanced.coordinator_model")
            self.assertEqual(explorer["native_effort"], "high")
            self.assertEqual(explorer["effort_source"], "model_presets.codex.balanced.effort.medium")

    def test_models_fetch_reports_unavailable_source_with_nonzero_json_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            result = self._run(
                root,
                "models",
                "fetch",
                "--target",
                "claude",
                "--format",
                "json",
                environment_overrides={"ANTHROPIC_API_KEY": ""},
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["status"], "unavailable")
            self.assertEqual(payload["source"], "anthropic-api-catalog")

    def test_models_fetch_empty_live_catalog_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            output = StringIO()
            empty_catalog = CatalogResult(
                "antigravity", "antigravity-cli", "unavailable", (),
                "agy returned no usable models",
            )
            with (
                patch("agent_team.cli.project_root", return_value=root),
                patch("agent_team.cli.fetch_catalog", return_value=empty_catalog),
                redirect_stdout(output),
            ):
                exit_code = cli.main([
                    "models", "fetch", "--target", "antigravity", "--format", "json",
                ])
            self.assertEqual(exit_code, 1)
            self.assertEqual(json.loads(output.getvalue())["status"], "unavailable")

    def test_validate_checks_overrides_for_disabled_configured_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            config = root / ".agent-team" / "team.toml"
            config.write_text(
                config.read_text(encoding="utf-8")
                .replace('enabled_targets = ["codex", "claude", "antigravity"]', 'enabled_targets = ["codex"]')
                + '\n[model_presets.claude.balanced]\ncoordinator_effort = "ultra"\n',
                encoding="utf-8",
            )
            result = self._run(root, "validate", "--format", "json")
            self.assertEqual(result.returncode, 1)
            diagnostics = json.loads(result.stdout)["diagnostics"]
            self.assertTrue(any(
                item["path"] == "model_presets.claude.balanced.coordinator_effort"
                for item in diagnostics
            ))

    def test_render_uses_only_an_explicit_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(Path(directory), "render", "--help")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--output OUTPUT", result.stdout)
            self.assertNotIn("--scope", result.stdout)

    def test_antigravity_user_install_uses_native_global_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as home:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            self.assertEqual(self._run(root, "init", "--scope", "user", environment_overrides={"HOME": home}).returncode, 0)
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

    def test_version_output_matches_available_version_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(Path(directory), "--version")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), f"agent-team {get_version()}")

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
            result = self._run(root, "init", "--scope", "project")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self._run(root, "generate").returncode, 0)

            # verify team.toml
            self.assertTrue((root / ".agent-team" / "team.toml").is_file())

            # verify configuration & scaffolding templates
            templates_dir = root / ".agent-team" / "templates"
            self.assertTrue((templates_dir / "profile" / "codex.toml.example").is_file())
            self.assertTrue((templates_dir / "role" / "coordinator" / "role.toml.example").is_file())
            self.assertTrue((templates_dir / "review" / "REVIEW.md.example").is_file())
            self.assertFalse((templates_dir / "prompt").exists())

            # verify gitignore entries
            gitignore_file = root / ".gitignore"
            self.assertTrue(gitignore_file.is_file())
            content = gitignore_file.read_text(encoding="utf-8")
            for entry in (
                ".worktrees/", ".agent-team/runs/", ".agent-team/backups/",
                ".agent-team/install-state.json",
                "/.agent-team/templates/role/",
                "/.agent-team/templates/profile/",
                "/.agent-team/templates/review/",
            ):
                self.assertIn(entry, content)

    def test_init_is_idempotent_and_preserves_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)

            # modify team.toml
            team_toml = root / ".agent-team" / "team.toml"
            custom_config = team_toml.read_text(encoding="utf-8") + "\n# custom comment\n"
            team_toml.write_text(custom_config, encoding="utf-8")

            self.assertEqual(self._run(root, "generate").returncode, 0)

            # modify one example template to verify update
            codex_example = root / ".agent-team" / "templates" / "profile" / "codex.toml.example"
            codex_example.write_text("modified", encoding="utf-8")

            # review example template is generated
            review_example = root / ".agent-team" / "templates" / "review" / "REVIEW.md.example"
            self.assertTrue(review_example.is_file())

            # customize REVIEW.md override to verify non-overwriting preservation
            custom_review_policy = "# custom project review rule\n"
            review_policy = root / ".agent-team" / "REVIEW.md"
            review_policy.write_text(custom_review_policy, encoding="utf-8")

            # run init again
            second = self._run(root, "init", "--scope", "project")
            self.assertEqual(second.returncode, 0, second.stderr)

            # team.toml is preserved
            self.assertEqual(team_toml.read_text(encoding="utf-8"), custom_config)

            self.assertEqual(self._run(root, "generate").returncode, 0)

            # modified template was updated/upserted
            self.assertNotEqual(codex_example.read_text(encoding="utf-8"), "modified")

            # customized REVIEW.md was preserved untouched
            self.assertEqual(review_policy.read_text(encoding="utf-8"), custom_review_policy)

            # gitignore entries are not duplicated
            gitignore_content = (root / ".gitignore").read_text(encoding="utf-8")
            for entry in (
                ".worktrees/", ".agent-team/runs/", ".agent-team/backups/",
                ".agent-team/install-state.json",
                "/.agent-team/templates/prompt/plan.md",
                "/.agent-team/templates/prompt/coordinate.md",
                "/.agent-team/templates/prompt/review.md",
                "/.agent-team/templates/prompt/discovery.md",
            ):
                self.assertEqual(gitignore_content.count(entry), 1)

    def test_init_upserts_partial_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gitignore = root / ".gitignore"
            gitignore.write_text("node_modules/\n/.agent-team/runs/\n.worktrees", encoding="utf-8")

            result = self._run(root, "generate", "gitignore")
            self.assertEqual(result.returncode, 0, result.stderr)

            content = gitignore.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("node_modules/\n/.agent-team/runs/\n.worktrees\n"))
            self.assertIn(".agent-team/backups/", content)
            self.assertIn(".agent-team/install-state.json", content)
            # Ensure existing entries were not duplicated
            lines = [line.strip().strip("/") for line in content.splitlines() if line.strip()]
            self.assertEqual(lines.count(".agent-team/runs"), 1)
            self.assertEqual(lines.count(".worktrees"), 1)

    def test_install_preset_flag_selects_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            result = self._run(root, "install", "--target", "codex", "--preset", "economy")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("economy preset", result.stdout)
            self.assertIn("preview only", result.stdout)

    def test_install_model_preset_alias_matches_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            primary = self._run(root, "install", "--target", "codex", "--model-preset", "economy")
            alias = self._run(root, "install", "--target", "codex", "--preset", "economy")
            self.assertEqual(primary.returncode, 0, primary.stderr)
            self.assertEqual(alias.returncode, 0, alias.stderr)
            self.assertEqual(primary.stdout, alias.stdout)

    def test_install_preset_and_run_are_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            result = self._run(
                root, "install", "--target", "codex", "--preset", "economy", "--run", "cli-run",
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("not allowed with argument", result.stderr)

    def test_install_rejects_malformed_preset_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            result = self._run(root, "install", "--target", "codex", "--preset", "Not A Preset")
            self.assertEqual(result.returncode, 2)
            self.assertIn("kebab-case", result.stderr)

    def test_install_rejects_preset_missing_from_target_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            result = self._run(root, "install", "--target", "codex", "--preset", "ghost")
            self.assertEqual(result.returncode, 2)
            self.assertIn("[enum] model_preset", result.stderr)
            self.assertIn("ghost", result.stderr)
            self.assertIn("available: economy, balanced, quality", result.stderr)

    def test_install_rejects_preset_missing_from_any_of_multiple_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            _define_custom_preset(root, "codex")
            rejected = self._run(
                root, "install", "--target", "codex,claude", "--preset", CUSTOM_PRESET_NAME,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("[enum] model_preset", rejected.stderr)
            self.assertIn(f"{CUSTOM_PRESET_NAME} is not defined by the claude profile", rejected.stderr)
            accepted = self._run(root, "install", "--target", "codex", "--preset", CUSTOM_PRESET_NAME)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertIn(f"{CUSTOM_PRESET_NAME} preset", accepted.stdout)

    def test_render_preset_flag_matches_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            result = self._run(
                root, "render", "--target", "codex", "--preset", "economy", "--output", "dist",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            coordinator = tomllib.loads(
                (root / "dist" / ".codex" / "agents" / "coordinator.toml").read_text(encoding="utf-8")
            )
            self.assertEqual(coordinator["model"], _builtin_preset("codex", "economy")["coordinator_model"])
            self.assertNotEqual(
                coordinator["model"], _builtin_preset("codex", "balanced")["coordinator_model"],
            )

    def test_run_init_accepts_custom_preset_and_rejects_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            _define_custom_preset(root, "codex")
            accepted = self._run(
                root, "run", "init", "--slug", "custom-preset-run",
                "--model-preset", CUSTOM_PRESET_NAME,
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            manifest = tomllib.loads(
                (root / ".agent-team" / "runs" / "custom-preset-run" / "run.toml").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["model_preset"], CUSTOM_PRESET_NAME)
            rejected = self._run(
                root, "run", "init", "--slug", "unknown-preset-run", "--model-preset", "ghost",
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("[enum] model_preset", rejected.stderr)
            self.assertFalse((root / ".agent-team" / "runs" / "unknown-preset-run").exists())

    def test_models_show_custom_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            _define_custom_preset(root, "codex")
            result = self._run(
                root, "models", "show", "--target", "codex",
                "--model-preset", CUSTOM_PRESET_NAME, "--format", "json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            target = json.loads(result.stdout)["targets"][0]
            self.assertEqual(target["preset"], CUSTOM_PRESET_NAME)
            coordinator = next(item for item in target["roles"] if item["role_id"] == "coordinator")
            self.assertEqual(coordinator["native_model"], CUSTOM_PRESET_COORDINATOR)
            self.assertEqual(
                coordinator["model_source"],
                f"model_presets.codex.{CUSTOM_PRESET_NAME}.coordinator_model",
            )

    def test_install_scope_user_honors_preset_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "user").returncode, 0)
            result = self._run(
                root, "install", "--scope", "user", "--target", "codex", "--preset", "quality",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("quality preset", result.stdout)

    def test_generate_gitignore_tolerates_custom_default_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            _set_default_preset(root, "codex", CUSTOM_PRESET_NAME)
            _define_custom_preset(root, "codex")
            self.assertNotIn(
                CUSTOM_PRESET_NAME,
                tomllib.loads(asset_text("definitions", "targets", "pi.toml"))["presets"],
            )
            result = self._run(root, "generate", "gitignore")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("upserted", result.stdout)

    def test_install_uses_per_target_default_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            _set_default_preset(root, "codex", "quality")
            codex = self._run(root, "install", "--target", "codex")
            self.assertEqual(codex.returncode, 0, codex.stderr)
            self.assertIn("quality preset", codex.stdout)
            claude = self._run(root, "install", "--target", "claude")
            self.assertEqual(claude.returncode, 0, claude.stderr)
            self.assertIn("balanced preset", claude.stdout)

    def test_install_applies_explicit_custom_preset_over_missing_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
            _set_default_preset(root, "codex", "missing")
            _define_custom_preset(root, "codex")
            result = self._run(root, "install", "--target", "codex", "--preset", CUSTOM_PRESET_NAME, "--apply")
            self.assertEqual(result.returncode, 0, result.stderr)
            coordinator = tomllib.loads((root / ".codex/agents/coordinator.toml").read_text())
            self.assertEqual(coordinator["model"], "spark-coordinator")
            self.assertEqual(self._run(root, "validate").returncode, 1)

    def test_install_does_not_generate_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init").returncode, 0)
            applied = self._run(root, "install", "--target", "codex,claude,antigravity", "--apply")
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertFalse((root / ".gitignore").exists())

    def test_install_ignores_custom_sources_destinations_and_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "init", "--scope", "project").returncode, 0)
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

            first = self._run(root, "install", "--target", "codex", "--apply")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(self._run(root, "generate", "gitignore").returncode, 0)
            ignore = root / ".gitignore"
            rules = ignore.read_text(encoding="utf-8").splitlines()
            self.assertIn("/.codex/generated\\[agents\\]/analyst.toml", rules)
            self.assertNotIn("/definitions/roles/analyst/role.toml", rules)

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
