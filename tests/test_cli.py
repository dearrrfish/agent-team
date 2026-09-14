import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
