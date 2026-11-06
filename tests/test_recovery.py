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

    def test_cli_fallback_is_not_used_for_session_only_selection(self):
        self.create_run()
        bound = self.runner(
            self.root, "resume", "bind", "--slug", "first",
            environment_overrides={"AGENT_TEAM_SESSION_ID": ""},
        )
        self.assertEqual(bound.returncode, 0, bound.stderr)
        self.create_run("second")
        candidates = discover_runs(self.root, self.config)
        selected, notices = select_run(candidates, self.root, session_id="unbound")
        self.assertEqual(selected.slug, "first")
        self.assertFalse(notices)
        selected, notices = select_run(
            candidates, self.root, session_id="unbound", session_only=True,
        )
        self.assertIsNone(selected)
        self.assertFalse(notices)

        # With no project pointer, the CLI still falls back to a single active
        # run; hooks do not.
        (self.root / ".agent-team/sessions/current.json").unlink()
        (self.root / ".agent-team/runs/second/run.toml").write_text(
            (self.root / ".agent-team/runs/second/run.toml").read_text(
                encoding="utf-8"
            ).replace('status = "discovery"', 'status = "complete"'),
            encoding="utf-8",
        )
        candidates = discover_runs(self.root, self.config)
        selected, notices = select_run(candidates, self.root, session_id="unbound")
        self.assertEqual(selected.slug, "first")
        self.assertFalse(notices)
        selected, notices = select_run(
            candidates, self.root, session_id="unbound", session_only=True,
        )
        self.assertIsNone(selected)
        self.assertFalse(notices)

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
            result = subprocess.run(["git", *args], check=False, cwd=self.root, capture_output=True)
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

    def test_review_policy_drift_and_reconcile(self):
        path = self.create_run()
        config_file = self.root / ".agent-team" / "team.toml"
        config_file.write_text(
            config_file.read_text(encoding="utf-8")
            .replace('re_review_mode = "diff-only"', 're_review_mode = "full-scope"')
            .replace("nit_cap = 2", "nit_cap = 1")
            .replace('policy_file = ".agent-team/REVIEW.md"', 'policy_file = "docs/REVIEW.md"'),
            encoding="utf-8",
        )
        config = load_team_config(self.root)
        candidate = discover_runs(self.root, config)[0]
        status = recovery_status(candidate, self.root, config)
        self.assertIn("review.re_review_mode: diff-only -> full-scope", status["config_drift"])
        self.assertIn("review.nit_cap: 2 -> 1", status["config_drift"])
        self.assertIn("review.policy_file: .agent-team/REVIEW.md -> docs/REVIEW.md", status["config_drift"])

        reconciled = self.runner(self.root, "run", "reconcile", "--slug", "first", "--apply")
        self.assertEqual(reconciled.returncode, 0, reconciled.stderr)
        updated_text = path.read_text(encoding="utf-8")
        self.assertIn('re_review_mode = "full-scope"', updated_text)
        self.assertIn("nit_cap = 1", updated_text)
        self.assertIn('policy_file = "docs/REVIEW.md"', updated_text)

    def test_prepare_review_and_review_binding_staleness(self):
        def git(*args):
            result = subprocess.run(["git", *args], check=False, cwd=self.root, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

        git("init")
        git("config", "user.email", "test@example.invalid")
        git("config", "user.name", "Test")
        tracked = self.root / "src.txt"
        tracked.write_text("v1\n", encoding="utf-8")
        git("add", "src.txt")
        git("-c", "commit.gpgsign=false", "commit", "-m", "baseline")

        result = self.runner(self.root, "run", "init", "--slug", "team-run", "--tier", "team")
        self.assertEqual(result.returncode, 0, result.stderr)
        tracked.write_text("v2\n", encoding="utf-8")

        packet_json_res = self.runner(
            self.root, "run", "prepare-review", "--slug", "team-run", "--format", "json"
        )
        self.assertEqual(packet_json_res.returncode, 0, packet_json_res.stderr)
        packet = json.loads(packet_json_res.stdout)
        self.assertEqual(packet["cycle"], 1)
        self.assertEqual(packet["review_mode"], "full-scope")
        self.assertTrue(packet["bug_class_sweep"])
        self.assertIn("M\tsrc.txt", packet["changed_files"])

        out_rel = Path(".agent-team/runs/team-run/reports/packet-c1.md")
        packet_md_res = self.runner(
            self.root,
            "run",
            "prepare-review",
            "--slug",
            "team-run",
            "--output",
            str(out_rel),
        )
        self.assertEqual(packet_md_res.returncode, 0, packet_md_res.stderr)
        self.assertTrue((self.root / out_rel).is_file())
        self.assertIn("## Recommended `review.md` Header Block", packet_md_res.stdout)

        # Bind review.md to the current workspace fingerprint as approved Cycle 1
        manifest_path = self.root / ".agent-team/runs/team-run/run.toml"
        manifest_path.write_text(
            manifest_path.read_text(encoding="utf-8")
            .replace("used = 0", "used = 1")
            .replace('verdict = "pending"', 'verdict = "approved"'),
            encoding="utf-8",
        )
        review_path = self.root / ".agent-team/runs/team-run/review.md"
        ws = packet["workspace"]
        review_path.write_text(
            f"# Review: team-run\n\n"
            f"- Run: `team-run`\n"
            f"- Cycle: 1\n"
            f"- Review-Mode: full-scope\n"
            f"- Base-Revision: {packet['base_revision']}\n"
            f"- Revision: {ws['revision']}\n"
            f"- Tracked-Diff-SHA256: {ws['tracked_diff_sha256']}\n"
            f"- Untracked-SHA256: {ws['untracked_sha256']}\n"
            f"- Updated: 2026-11-06T00:00:00Z\n"
            f"- Verdict: approved\n\n"
            f"## Scope and evidence\n\nReviewed v2.\n\n"
            f"## Findings\n\n| ID | Severity / Category | Bug class & finding | Disposition & required fix |\n| --- | --- | --- | --- |\n| C1-F001 | low / Nit | minor | open |\n\n"
            f"## Residual risks and gaps\n\nNone.\n",
            encoding="utf-8",
        )

        config = load_team_config(self.root)
        candidate = [c for c in discover_runs(self.root, config) if c.slug == "team-run"][0]
        status_bound = recovery_status(candidate, self.root, config)
        self.assertEqual(status_bound["review_binding"]["state"], "bound")

        # Modify workspace after approval -> review_binding becomes stale
        tracked.write_text("v3\n", encoding="utf-8")
        status_stale = recovery_status(candidate, self.root, config)
        self.assertEqual(status_stale["review_binding"]["state"], "stale")
        self.assertIn("prepare-review", status_stale["next"])

        # Prepare Cycle 2 packet -> automatically selects diff-only and includes prior findings
        c2_res = self.runner(
            self.root, "run", "prepare-review", "--slug", "team-run", "--format", "json"
        )
        self.assertEqual(c2_res.returncode, 0, c2_res.stderr)
        c2_packet = json.loads(c2_res.stdout)
        self.assertEqual(c2_packet["cycle"], 2)
        self.assertEqual(c2_packet["review_mode"], "diff-only")
        self.assertFalse(c2_packet["bug_class_sweep"])
        self.assertIn("C1-F001", c2_packet["prior_findings"])
