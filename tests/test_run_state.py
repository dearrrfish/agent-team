import json
import subprocess
import sys
import tomllib

from agent_team.recovery import classify_evidence, discover_runs, recovery_status
from agent_team.runs import validate_run
from tests import test_recovery
import unittest


class RunStateTests(unittest.TestCase):
    setUp = test_recovery.RecoveryTests.setUp
    create_run = test_recovery.RecoveryTests.create_run
    def test_claim_release_and_token(self):
        path = self.create_run()
        path.write_text(path.read_text() + '\n[[tasks]]\nid = "T-001"\ngroup = "TG-01"\nrole = "implementer"\ninstance = "worker"\nstatus = "running"\ndeps = []\nreport = "reports/T-001-implementer.md"\n')
        result = self.runner(self.root, "run", "lease", "claim", "--slug", "first",
                             "--task", "T-001", "--owner", "worker", "--owned-path", "src")
        self.assertEqual(result.returncode, 0, result.stderr)
        token = result.stdout.strip()
        self.assertEqual(tomllib.loads(path.read_text())["tasks"][0]["lease"]["token"], token)
        self.assertFalse([d for d in validate_run(path, self.config) if d.severity == "error"])
        again = self.runner(self.root, "run", "lease", "claim", "--slug", "first",
                            "--task", "T-001", "--owner", "worker", "--owned-path", "src")
        self.assertEqual(again.returncode, 2)
        before = path.read_bytes()
        wrong = self.runner(self.root, "run", "lease", "release", "--slug", "first",
                            "--task", "T-001", "--token", "wrong")
        self.assertEqual(wrong.returncode, 2)
        self.assertEqual(path.read_bytes(), before)
        released = self.runner(self.root, "run", "lease", "release", "--slug", "first",
                               "--task", "T-001", "--token", token)
        self.assertEqual(released.returncode, 0, released.stderr)
        self.assertNotIn("lease", tomllib.loads(path.read_text())["tasks"][0])
        path.write_text(path.read_text().replace("worker_closure = false", "worker_closure = true"))
        self.assertTrue(any(d.code == "gate" for d in validate_run(path, self.config)))

    def test_verify_binding_failure_and_stale(self):
        path = self.create_run()
        (self.root / ".gitignore").write_text(".agent-team/\nisolated-home/\n")
        def git(*args):
            result = subprocess.run(["git", *args], cwd=self.root, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        git("init")
        git("add", ".gitignore")
        git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-m", "base")
        result = self.runner(self.root, "run", "verify", "--slug", "first", "--producer", "test",
                             "--", sys.executable, "-c", "pass")
        self.assertEqual(result.returncode, 0, result.stderr)
        candidate = discover_runs(self.root, self.config)[0]
        self.assertEqual(recovery_status(candidate, self.root, self.config)["evidence"][0]["state"], "bound")
        (self.root / "new.txt").write_text("changed")
        self.assertEqual(recovery_status(candidate, self.root, self.config)["evidence"][0]["state"], "stale")
        result = self.runner(self.root, "run", "verify", "--slug", "first", "--producer", "test",
                             "--", sys.executable, "-c", "raise SystemExit(5)")
        self.assertEqual(result.returncode, 5)
        records = tomllib.loads(path.read_text())["verification"]
        self.assertEqual(records[-1]["exit_status"], 5)
        self.assertFalse([d for d in validate_run(path, self.config) if d.severity == "error"])
        self.assertEqual(classify_evidence({"verification": records}, {"revision": "unknown"})[-1]["state"], "failed")

    def test_check_mutation_is_unbound_and_bad_records_rejected(self):
        path = self.create_run()
        result = self.runner(self.root, "run", "verify", "--slug", "first", "--producer", "test",
                             "--", sys.executable, "-c", "from pathlib import Path; Path('changed').write_text('x')")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = tomllib.loads(path.read_text())["verification"][0]
        self.assertEqual(record["revision"], "unknown")
        result = self.runner(self.root, "run", "verify", "--slug", "first", "--producer", "test",
                             "--cwd", "../", "--", sys.executable, "-c", "pass")
        self.assertEqual(result.returncode, 2)
        path.write_text(path.read_text().replace('exit_status = 0', 'exit_status = true'))
        self.assertTrue(any(d.path.endswith("exit_status") and d.severity == "error"
                            for d in validate_run(path, self.config)))

    def test_tracked_run_manifest_does_not_invalidate_evidence(self):
        path = self.create_run()
        def git(*args):
            result = subprocess.run(["git", *args], cwd=self.root, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        git("init")
        git("add", "-A")
        git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-m", "base")
        for _ in range(2):
            result = self.runner(self.root, "run", "verify", "--slug", "first", "--producer", "test",
                                 "--", sys.executable, "-c", "pass")
            self.assertEqual(result.returncode, 0, result.stderr)
        candidate = discover_runs(self.root, self.config)[0]
        self.assertEqual(recovery_status(candidate, self.root, self.config)["evidence"][-1]["state"], "bound")
        (self.root / "source.py").write_text("x = 1\n")
        git("add", "source.py")
        self.assertEqual(recovery_status(candidate, self.root, self.config)["evidence"][-1]["state"], "stale")

    def test_bind_and_reconcile(self):
        path = self.create_run()
        self.create_run("second")
        result = self.runner(self.root, "resume", "bind", "--slug", "first", "--session-id", "s")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.runner(self.root, "resume", "--session-id", "s", "--json")
        self.assertEqual(json.loads(result.stdout)["selected"]["slug"], "first")
        path.write_text(path.read_text().replace("max_workers = 2", "max_workers = 1 # preserved"))
        before = path.read_bytes()
        result = self.runner(self.root, "run", "reconcile", "--slug", "first")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_bytes(), before)
        result = self.runner(self.root, "run", "reconcile", "--slug", "first", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("max_workers = 2 # preserved", path.read_text())

