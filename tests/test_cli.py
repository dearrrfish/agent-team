import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = str(Path(__file__).parents[1] / "src")


class CliTests(unittest.TestCase):
    def _run(self, root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = SOURCE
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
            run = self._run(root, "run", "init", "--slug", "cli-run", "--tier", "assisted")
            self.assertEqual(run.returncode, 0, run.stderr)
            render = self._run(root, "render", "--target", "codex", "--output", "dist")
            self.assertEqual(render.returncode, 0, render.stderr)
            preview = self._run(root, "install", "--target", "codex")
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn("preview only", preview.stdout)
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


if __name__ == "__main__":
    unittest.main()
