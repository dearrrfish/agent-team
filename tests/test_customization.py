import tempfile
import tomllib
import unittest
from pathlib import Path

from agent_team.adapters import render_target
from agent_team.config import DEFAULT_TEAM_TOML, load_roles, load_team_config
from agent_team.diagnostics import ValidationFailure
from agent_team.runs import init_run, validate_run

CUSTOM_ROLE = '''schema_version = 1
id = "analyst"
description = "Analyzes a bounded domain question."
instructions = "instructions.md"
model_class = "balanced"
effort = "medium"
write_policy = "deny"
delegation = false
max_turns = 12
report_kind = "agent-report"
capabilities = ["filesystem.read", "docs.read"]

[activation]
use_when = "A bounded analysis needs a dedicated role."
avoid_when = "The task requires changes."
'''


class CustomizationTests(unittest.TestCase):
    def _project(self, config_text: str = DEFAULT_TEAM_TOML) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / ".agent-team").mkdir()
        (root / ".agent-team" / "team.toml").write_text(config_text, encoding="utf-8")
        return temporary

    def test_custom_role_source_adds_native_agent(self) -> None:
        config_text = DEFAULT_TEAM_TOML.replace(
            'role_sources = ["builtin:roles"]',
            'role_sources = ["builtin:roles", "definitions/roles"]',
        )
        with self._project(config_text) as directory:
            root = Path(directory)
            role_dir = root / "definitions" / "roles" / "analyst"
            role_dir.mkdir(parents=True)
            (role_dir / "role.toml").write_text(CUSTOM_ROLE, encoding="utf-8")
            (role_dir / "instructions.md").write_text(
                "# Position and outcome\n\nAnalyze the assigned question.\n", encoding="utf-8"
            )
            config = load_team_config(root)
            self.assertIn("analyst", {role.role_id for role in load_roles(config, root)})
            rendered = render_target("codex", config, root)
            analyst_path = next(path for path in rendered if str(path).endswith("analyst.toml"))
            analyst = tomllib.loads(rendered[analyst_path])
            self.assertIn("Use when: A bounded analysis", analyst["description"])
            self.assertIn("Avoid when: The task requires changes", analyst["description"])
            self.assertIn("within at most 12 turns", analyst["developer_instructions"])
            self.assertIn("`agent-report` report contract", analyst["developer_instructions"])

    def test_deep_discovery_adds_design_artifact_and_opens_gate(self) -> None:
        config_text = DEFAULT_TEAM_TOML.replace(
            "deep_discovery_default = false", "deep_discovery_default = true"
        )
        with self._project(config_text) as directory:
            root = Path(directory)
            config = load_team_config(root)
            run_dir = init_run(root, config, "deep-run", None, "assisted", "balanced")
            self.assertTrue((run_dir / "design.md").is_file())
            self.assertTrue((run_dir / "decisions.md").is_file())
            manifest = (run_dir / "run.toml").read_text(encoding="utf-8")
            self.assertIn('design = "design.md"', manifest)
            self.assertIn('decisions = "decisions.md"', manifest)
            self.assertIn("design = false", manifest)

            manifest_path = run_dir / "run.toml"
            bypass = manifest.replace("design = false", "design = true")
            bypass = bypass.replace('design = "design.md"\n', "")
            bypass = bypass.replace('decisions = "decisions.md"\n', "")
            manifest_path.write_text(bypass, encoding="utf-8")
            diagnostics = validate_run(manifest_path, config)
            required_paths = {
                item.path.rsplit(".", 1)[-1]
                for item in diagnostics
                if item.code == "required"
            }
            self.assertTrue({"design", "decisions"}.issubset(required_paths))

    def test_report_persistence_is_optional_except_for_team_runs(self) -> None:
        config_text = DEFAULT_TEAM_TOML.replace(
            "persist_agent_reports = true", "persist_agent_reports = false"
        )
        with self._project(config_text) as directory:
            root = Path(directory)
            config = load_team_config(root)
            assisted = init_run(root, config, "no-reports", None, "assisted", "balanced")
            self.assertFalse((assisted / "reports").exists())
            assisted_manifest = assisted / "run.toml"
            self.assertIn("reports_required = false", assisted_manifest.read_text(encoding="utf-8"))
            with assisted_manifest.open("a", encoding="utf-8") as handle:
                handle.write('''
[[tasks]]
id = "T-001"
group = "TG-01"
role = "implementer"
instance = "one"
status = "complete"
deps = []
''')
            diagnostics = validate_run(assisted_manifest, config)
            self.assertFalse(any(item.path.endswith(".report") for item in diagnostics))

            team = init_run(root, config, "team-reports", None, "team", "balanced")
            self.assertTrue((team / "reports").is_dir())
            self.assertIn("reports_required = true", (team / "run.toml").read_text(encoding="utf-8"))

            solo = init_run(root, config, "solo-no-reports", None, "solo", "balanced")
            self.assertFalse((solo / "reports").exists())
            self.assertIn("reports_required = false", (solo / "run.toml").read_text(encoding="utf-8"))

    def test_invalid_profile_path_is_rejected_before_loading(self) -> None:
        config_text = DEFAULT_TEAM_TOML.replace(
            'codex = "builtin:codex"', 'codex = "../codex.toml"'
        )
        with self._project(config_text) as directory:
            with self.assertRaises(ValidationFailure) as context:
                load_team_config(Path(directory))
            self.assertTrue(any(item.path == "target_profiles.codex" for item in context.exception.diagnostics))

    def test_reviewing_team_requires_at_least_one_completed_task(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            config = load_team_config(root)
            run_dir = init_run(root, config, "empty-review", None, "team", "balanced")
            manifest = run_dir / "run.toml"
            text = manifest.read_text(encoding="utf-8")
            text = text.replace('status = "discovery"', 'status = "reviewing"')
            text = text.replace("requirements = false", "requirements = true")
            text = text.replace("plan = false", "plan = true")
            text = text.replace("worker_closure = false", "worker_closure = true")
            manifest.write_text(text, encoding="utf-8")
            diagnostics = validate_run(manifest, config)
            self.assertTrue(any(item.path.endswith(".tasks") and item.code == "gate" for item in diagnostics))

    def test_assisted_review_policy_generates_and_requires_review_artifact(self) -> None:
        config_text = DEFAULT_TEAM_TOML.replace(
            "[tiers.assisted]\nmax_workers = 2\ndurable_artifacts = true\nindependent_review = false",
            "[tiers.assisted]\nmax_workers = 2\ndurable_artifacts = true\nindependent_review = true",
        )
        with self._project(config_text) as directory:
            root = Path(directory)
            config = load_team_config(root)
            run_dir = init_run(root, config, "assisted-review", None, "assisted", "balanced")
            self.assertTrue((run_dir / "review.md").is_file())
            manifest = run_dir / "run.toml"
            text = manifest.read_text(encoding="utf-8")
            self.assertIn('review = "review.md"', text)
            manifest.write_text(text.replace('review = "review.md"\n', ""), encoding="utf-8")
            diagnostics = validate_run(manifest, config)
            self.assertTrue(any(
                item.path.endswith(".artifacts.review") and item.code == "required"
                for item in diagnostics
            ))


if __name__ == "__main__":
    unittest.main()
