import tempfile
import tomllib
import unittest
from pathlib import Path

from agent_team.config import DEFAULT_TEAM_TOML, load_team_config
from agent_team.diagnostics import ValidationFailure
from agent_team.runs import init_run, validate_run
from agent_team.templates import TemplateError, render_template, required_markers


class TemplateAndRunTests(unittest.TestCase):
    def _project(self) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / ".agent-team").mkdir()
        (root / ".agent-team" / "team.toml").write_text(DEFAULT_TEAM_TOML, encoding="utf-8")
        return temporary

    def test_template_substitution_is_strict(self) -> None:
        self.assertEqual(render_template("hello ${name}", {"name": "team"}), "hello team")
        self.assertEqual(render_template("${body}", {"body": "literal ${name}"}), "literal ${name}")
        with self.assertRaises(TemplateError):
            render_template("hello ${name}", {})
        self.assertEqual(len(required_markers("<!-- REQUIRED: fill me -->")), 1)

    def test_team_run_has_expected_artifacts_and_warning_markers(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            config = load_team_config(root)
            run_dir = init_run(root, config, "native-team", "Native Team", "team", "balanced")
            expected = {"run.toml", "requirements.md", "plan.md", "tasks.md", "review.md", "final-report.md", "reports"}
            self.assertEqual({path.name for path in run_dir.iterdir()}, expected)
            manifest_data = tomllib.loads((run_dir / "run.toml").read_text(encoding="utf-8"))
            self.assertEqual(manifest_data["max_workers"], 4)
            self.assertTrue(manifest_data["reports_required"])
            self.assertFalse(manifest_data["gates"]["live_validation"])
            diagnostics = validate_run(run_dir / "run.toml", config)
            self.assertFalse(any(item.severity == "error" for item in diagnostics))
            self.assertTrue(any(item.code == "required-marker" for item in diagnostics))

    def test_duplicate_run_and_invalid_slug_are_refused(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            config = load_team_config(root)
            init_run(root, config, "one-run", None, "assisted", "balanced")
            with self.assertRaises(ValidationFailure):
                init_run(root, config, "one-run", None, "assisted", "balanced")
            with self.assertRaises(ValidationFailure):
                init_run(root, config, "../escape", None, "assisted", "balanced")

    def test_completion_enforces_gates_review_and_markers(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            config = load_team_config(root)
            run_dir = init_run(root, config, "complete-check", None, "team", "balanced")
            manifest = run_dir / "run.toml"
            text = manifest.read_text(encoding="utf-8").replace('status = "discovery"', 'status = "complete"')
            manifest.write_text(text, encoding="utf-8")
            diagnostics = validate_run(manifest, config)
            codes = {item.code for item in diagnostics if item.severity == "error"}
            self.assertIn("gate", codes)
            self.assertIn("required-marker", codes)

    def test_task_dag_rejects_unknown_dependency_and_cycle(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            config = load_team_config(root)
            run_dir = init_run(root, config, "dag-check", None, "team", "balanced")
            manifest = run_dir / "run.toml"
            with manifest.open("a", encoding="utf-8") as handle:
                handle.write('''
[[tasks]]
id = "T-001"
group = "TG-01"
role = "implementer"
instance = "one"
status = "pending"
deps = ["T-002"]
report = "reports/T-001-implementer.md"

[[tasks]]
id = "T-002"
group = "TG-01"
role = "implementer"
instance = "two"
status = "pending"
deps = ["T-001", "T-999"]
report = "reports/T-002-implementer.md"
''')
            diagnostics = validate_run(manifest, config)
            self.assertTrue(any(item.code == "cycle" for item in diagnostics))
            self.assertTrue(any(item.code == "reference" for item in diagnostics))

    def test_task_state_requires_completed_dependencies_and_unique_instances(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            config = load_team_config(root)
            run_dir = init_run(root, config, "task-state", None, "team", "balanced")
            manifest = run_dir / "run.toml"
            with manifest.open("a", encoding="utf-8") as handle:
                handle.write('''
[[tasks]]
id = "T-001"
group = "TG-01"
role = "implementer"
instance = "duplicate"
status = "pending"
deps = []
report = "reports/T-001-implementer.md"

[[tasks]]
id = "T-002"
group = "TG-01"
role = "implementer"
instance = "duplicate"
status = "running"
deps = ["T-001"]
report = "reports/T-002-implementer.md"
''')
            diagnostics = validate_run(manifest, config)
            self.assertTrue(any(item.code == "dependency-state" for item in diagnostics))
            self.assertTrue(any(item.code == "duplicate" and item.path.endswith(".instance") for item in diagnostics))

    def test_review_verdict_requires_a_recorded_cycle(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            config = load_team_config(root)
            run_dir = init_run(root, config, "review-cycle", None, "team", "balanced")
            manifest = run_dir / "run.toml"
            text = manifest.read_text(encoding="utf-8").replace(
                'verdict = "pending"', 'verdict = "approved"'
            )
            manifest.write_text(text, encoding="utf-8")
            diagnostics = validate_run(manifest, config)
            self.assertTrue(any(
                item.path.endswith(".review.used") and item.code == "invariant"
                for item in diagnostics
            ))

    def test_running_tasks_cannot_exceed_configured_worker_limit(self) -> None:
        config_text = DEFAULT_TEAM_TOML.replace(
            "[tiers.team]\nmax_workers = 4",
            "[tiers.team]\nmax_workers = 2",
        )
        with self._project() as directory:
            root = Path(directory)
            (root / ".agent-team" / "team.toml").write_text(config_text, encoding="utf-8")
            config = load_team_config(root)
            run_dir = init_run(root, config, "worker-limit", None, "team", "balanced")
            manifest = run_dir / "run.toml"
            with manifest.open("a", encoding="utf-8") as handle:
                for number in range(1, 4):
                    handle.write(f'''
[[tasks]]
id = "T-{number:03d}"
group = "TG-01"
role = "implementer"
instance = "worker-{number}"
status = "running"
deps = []
report = "reports/T-{number:03d}-implementer.md"
''')
            diagnostics = validate_run(manifest, config)
            self.assertTrue(any(item.code == "worker-limit" for item in diagnostics))

    def test_completed_task_report_required_markers_are_validated(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            config = load_team_config(root)
            run_dir = init_run(root, config, "report-markers", None, "team", "balanced")
            manifest = run_dir / "run.toml"
            with manifest.open("a", encoding="utf-8") as handle:
                handle.write('''
[[tasks]]
id = "T-001"
group = "TG-01"
role = "implementer"
instance = "one"
status = "complete"
deps = []
report = "reports/T-001-implementer.md"
''')
            report = run_dir / "reports" / "T-001-implementer.md"
            report.write_text("<!-- REQUIRED: add verification evidence -->\n", encoding="utf-8")
            diagnostics = validate_run(manifest, config)
            self.assertTrue(any(
                item.path.endswith(".tasks.0.report")
                and item.code == "required-marker"
                and item.severity == "warning"
                for item in diagnostics
            ))
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace(
                    'status = "discovery"', 'status = "complete"'
                ),
                encoding="utf-8",
            )
            diagnostics = validate_run(manifest, config)
            self.assertTrue(any(
                item.path.endswith(".tasks.0.report")
                and item.code == "required-marker"
                and item.severity == "error"
                for item in diagnostics
            ))


if __name__ == "__main__":
    unittest.main()
