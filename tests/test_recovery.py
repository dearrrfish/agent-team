import hashlib
import json
import socket
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from agent_team.config import load_team_config
from agent_team.diagnostics import ValidationFailure
from agent_team.recovery import (
    classify_workers,
    discover_runs,
    fingerprint_workspace,
    recovery_status,
    render_context,
    select_run,
)
from tests import test_cli


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.runner = test_cli.CliTests()._run
        result = self.runner(self.root, "init", "--scope", "project")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.config = load_team_config(self.root)

    def create_run(self, slug="first"):
        result = self.runner(self.root, "run", "init", "--slug", slug, "--tier", "assisted")
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.root / ".agent-team" / "runs" / slug / "run.toml"

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob("*") if p.is_file()}

    def test_cli_selection_and_read_only(self):
        self.create_run()
        before = self.snapshot()
        for args in (("resume",), ("resume", "status", "--json"),
                     ("resume", "context", "--slug", "first")):
            result = self.runner(self.root, *args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("first", result.stdout)
        self.assertEqual(before, self.snapshot())
        self.create_run("second")
        result = self.runner(self.root, "resume", "--json")
        self.assertEqual(result.returncode, 3)
        self.assertIsNone(json.loads(result.stdout)["selected"])
        result = self.runner(self.root, "resume", "--slug", "first", "status", "--json")
        self.assertEqual(json.loads(result.stdout)["selected"]["slug"], "first")

    def test_empty_and_invalid_slug(self):
        self.assertEqual(self.runner(self.root, "resume").returncode, 0)
        self.assertEqual(self.runner(self.root, "resume", "--slug", "../bad").returncode, 2)
        self.assertEqual(self.runner(self.root, "resume", "--slug", "missing").returncode, 2)

    def test_corrupt_manifest_is_visible_and_not_resumed(self):
        path = self.create_run()
        path.write_text("invalid = [", encoding="utf-8")
        candidates = discover_runs(self.root, self.config)
        self.assertTrue(candidates[0].errors)
        result = self.runner(self.root, "resume", "--slug", "first")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unreadable", result.stderr)

    def test_pointer_identity_and_fallback(self):
        self.create_run()
        self.create_run("second")
        candidates = discover_runs(self.root, self.config)
        sessions = self.root / ".agent-team" / "sessions"
        sessions.mkdir()
        digest = hashlib.sha256(b"session").hexdigest()[:16]
        pointer = sessions / (digest + ".json")
        data = {"session_id_hash": digest, "project_root": str(self.root),
                "run_slug": "second", "run_path": ".agent-team/runs/second"}
        pointer.write_text(json.dumps(data), encoding="utf-8")
        selected, notices = select_run(candidates, self.root, session_id="session")
        self.assertEqual(selected.slug, "second")
        self.assertFalse(notices)
        data["project_root"] = "/another/project"
        pointer.write_text(json.dumps(data), encoding="utf-8")
        selected, notices = select_run(candidates, self.root, session_id="session")
        self.assertIsNone(selected)
        self.assertTrue(notices)

    def test_symlink_run_cannot_escape(self):
        with tempfile.TemporaryDirectory() as other:
            run_root = self.root / ".agent-team" / "runs"
            run_root.mkdir()
            (run_root / "escape").symlink_to(other, target_is_directory=True)
            candidates = discover_runs(self.root, self.config)
            self.assertIn("escapes", candidates[0].errors[0])
            with self.assertRaises(ValidationFailure):
                recovery_status(candidates[0], self.root, self.config)

    def test_worker_uncertainty_and_bound_context(self):
        path = self.create_run()
        path.write_text(path.read_text() + '\n[[tasks]]\nid = "T-001"\nstatus = "running"\n',
                        encoding="utf-8")
        candidate = discover_runs(self.root, self.config)[0]
        candidate.manifest["max_workers"] = 99
        status = recovery_status(candidate, self.root, self.config)
        self.assertTrue(status["config_drift"])
        self.assertEqual(status["workers"][0]["state"], "unknown")
        text = render_context(status)
        self.assertIn("暂停所有写操作", text)
        self.assertIn("unbound", text)
        status["workers"] *= 10000
        text = render_context(status)
        self.assertLessEqual(len(text), 9000)
        self.assertIn("暂停所有写操作", text)
        self.assertIn("Next:", text)
        status["path"] = "x" * 10000
        self.assertIn("暂停所有写操作", render_context(status))

    def test_worker_lease_is_not_liveness(self):
        now = datetime.now(UTC)
        task = {"id": "T-001", "status": "running", "lease": {
            "host": socket.gethostname(), "owner": "worker", "token": "token",
            "claimed_at": now.isoformat(), "last_observed_at": now.isoformat(),
            "owned_paths": ["src/"]}}
        self.assertEqual(classify_workers({"tasks": [task]}, now)[0]["state"], "live_unverified")
        task["lease"]["host"] = "another-host"
        self.assertEqual(classify_workers({"tasks": [task]}, now)[0]["state"], "unknown")
        task["status"] = "complete"
        self.assertEqual(classify_workers({"tasks": [task]}, now)[0]["state"], "unknown")

    def test_git_fingerprint_tracks_staged_and_untracked_changes(self):
        def git(*args):
            result = subprocess.run(["git", *args], cwd=self.root, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        git("init")
        git("config", "user.email", "test@example.invalid")
        git("config", "user.name", "Test")
        file = self.root / "tracked.txt"
        file.write_text("before")
        git("add", "tracked.txt")
        git("-c", "commit.gpgsign=false", "commit", "-m", "baseline")
        before = fingerprint_workspace(self.root)
        file.write_text("after")
        git("add", "tracked.txt")
        after = fingerprint_workspace(self.root)
        self.assertNotEqual(before.tracked_diff_sha256, after.tracked_diff_sha256)
        (self.root / "new.txt").write_text("new")
        self.assertNotEqual(after.untracked_sha256, fingerprint_workspace(self.root).untracked_sha256)

    def test_malformed_status_does_not_raise_type_error(self):
        path = self.create_run()
        path.write_text(path.read_text().replace('status = "discovery"', 'status = []'))
        result = self.runner(self.root, "resume", "--slug", "first")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(classify_workers({"tasks": [{"status": []}]})[0]["state"], "unknown")

    def test_terminal_runs_require_explicit_selection(self):
        path = self.create_run()
        path.write_text(path.read_text().replace('status = "discovery"', 'status = "complete"'))
        result = self.runner(self.root, "resume", "--json")
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(json.loads(result.stdout)["selected"])
        result = self.runner(self.root, "resume", "context", "--slug", "first")
        self.assertEqual(result.returncode, 0)
        self.assertIn("first", result.stdout)

    def test_non_git_fingerprint_is_unknown(self):
        self.assertEqual(fingerprint_workspace(self.root).revision, "unknown")
