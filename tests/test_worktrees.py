from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_team.worktrees import (
    WorktreeStatus,
    clean_worktree,
    detect_associated_slug,
    get_base_branch,
    list_worktrees,
    sync_run_artifacts,
)

SOURCE = str(Path(__file__).parents[1] / "src")


class TestWorktrees(unittest.TestCase):
    def _run(self, root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = SOURCE
        environment["HOME"] = str(root / "isolated-home")
        return subprocess.run(
            ["python3", "-m", "agent_team", *arguments],
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name).resolve()
        # Initialize a real git repo
        subprocess.run(["git", "init", "-b", "main", str(self.repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Tester"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "tester@example.com"], check=True)
        # Create initial commit
        (self.repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "initial commit"], check=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_get_base_branch(self) -> None:
        branch = get_base_branch(self.repo)
        self.assertEqual(branch, "main")

    def test_detect_associated_slug(self) -> None:
        wt_path = self.repo / ".worktrees" / "my-task"
        wt_path.mkdir(parents=True)
        # Run directory exists inside worktree
        (wt_path / ".agent-team" / "runs" / "auth-slug").mkdir(parents=True)
        slug = detect_associated_slug(wt_path, branch="feature/foo", repo_path=self.repo)
        self.assertEqual(slug, "auth-slug")

        # Branch name convention
        slug2 = detect_associated_slug(self.repo / "other", branch="agent-team/billing/task-1", repo_path=self.repo)
        self.assertEqual(slug2, "billing")

        # Matching run in main repo
        (self.repo / ".agent-team" / "runs" / "perf-run").mkdir(parents=True)
        slug3 = detect_associated_slug(self.repo / ".worktrees" / "perf-run-worker", branch="worker", repo_path=self.repo)
        self.assertEqual(slug3, "perf-run")

    def test_list_and_clean_worktrees_lifecycle(self) -> None:
        # Create worktrees directory
        wt_dir = self.repo / ".worktrees"
        wt_clean = wt_dir / "clean-wt"
        wt_ahead = wt_dir / "ahead-wt"
        wt_dirty = wt_dir / "dirty-wt"

        # 1. Clean & merged worktree
        subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "add", "-b", "branch-clean", str(wt_clean)],
            check=True, capture_output=True
        )

        # 2. Ahead worktree
        subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "add", "-b", "branch-ahead", str(wt_ahead)],
            check=True, capture_output=True
        )
        (wt_ahead / "ahead.txt").write_text("ahead\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(wt_ahead), "add", "ahead.txt"], check=True)
        subprocess.run(["git", "-C", str(wt_ahead), "commit", "-m", "ahead commit"], check=True)

        # 3. Dirty worktree
        subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "add", "-b", "branch-dirty", str(wt_dirty)],
            check=True, capture_output=True
        )
        (wt_dirty / "uncommitted.txt").write_text("dirty\n", encoding="utf-8")

        # Inspect with list_worktrees
        wts = list_worktrees(self.repo)
        by_path = {wt.path.name: wt for wt in wts}

        self.assertIn("clean-wt", by_path)
        self.assertEqual(by_path["clean-wt"].status, WorktreeStatus.CLEAN_MERGED)

        self.assertIn("ahead-wt", by_path)
        self.assertEqual(by_path["ahead-wt"].status, WorktreeStatus.AHEAD)

        self.assertIn("dirty-wt", by_path)
        self.assertEqual(by_path["dirty-wt"].status, WorktreeStatus.DIRTY)

        # Clean dirty without discard_changes should be BLOCKED
        res_dirty = clean_worktree(self.repo, by_path["dirty-wt"])
        self.assertFalse(res_dirty.success)
        self.assertEqual(res_dirty.action, "blocked")

        # Clean ahead without force should be BLOCKED
        res_ahead = clean_worktree(self.repo, by_path["ahead-wt"])
        self.assertFalse(res_ahead.success)
        self.assertEqual(res_ahead.action, "blocked")

        # Clean merged worktree should SUCCEED
        res_clean = clean_worktree(self.repo, by_path["clean-wt"])
        self.assertTrue(res_clean.success)
        self.assertEqual(res_clean.action, "removed")
        self.assertFalse(wt_clean.exists())

        # Clean dirty with discard_changes should SUCCEED
        res_dirty_forced = clean_worktree(self.repo, by_path["dirty-wt"], discard_changes=True)
        self.assertTrue(res_dirty_forced.success)
        self.assertFalse(wt_dirty.exists())

        # Clean ahead with force should SUCCEED
        res_ahead_forced = clean_worktree(self.repo, by_path["ahead-wt"], force=True)
        self.assertTrue(res_ahead_forced.success)
        self.assertFalse(wt_ahead.exists())

    def test_sync_run_artifacts(self) -> None:
        wt_path = self.repo / ".worktrees" / "worker-1"
        subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "add", "-b", "branch-worker", str(wt_path)],
            check=True, capture_output=True
        )
        # Inside worktree, create run artifacts
        wt_run_dir = wt_path / ".agent-team" / "runs" / "test-run" / "reports"
        wt_run_dir.mkdir(parents=True)
        (wt_run_dir / "task-01.md").write_text("# Report 01\nVerified.\n", encoding="utf-8")

        # Sync back to main repo
        synced = sync_run_artifacts(wt_path, self.repo, slug="test-run")
        self.assertEqual(len(synced), 1)

        expected_dest = self.repo / ".agent-team" / "runs" / "test-run" / "reports" / "task-01.md"
        self.assertTrue(expected_dest.is_file())
        self.assertIn("Verified.", expected_dest.read_text(encoding="utf-8"))

    def test_clean_worktree_dry_run(self) -> None:
        wt_path = self.repo / ".worktrees" / "dry-run-wt"
        subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "add", "-b", "branch-dry", str(wt_path)],
            check=True, capture_output=True
        )
        info = [w for w in list_worktrees(self.repo) if w.path.name == "dry-run-wt"][0]
        res = clean_worktree(self.repo, info, dry_run=True)
        self.assertTrue(res.success)
        self.assertEqual(res.action, "would-remove")
        self.assertTrue(wt_path.exists())  # Must NOT be deleted in dry-run!

    def test_cli_worktree_commands(self) -> None:
        # Initialize agent-team in this repo
        init_res = self._run(self.repo, "init", "--scope", "project")
        self.assertEqual(init_res.returncode, 0, init_res.stderr)

        # Add a clean worktree
        wt_path = self.repo / ".worktrees" / "cli-wt"
        subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "add", "-b", "branch-cli", str(wt_path)],
            check=True, capture_output=True
        )

        # Test CLI worktree list json
        list_res = self._run(self.repo, "worktree", "list", "--format", "json")
        self.assertEqual(list_res.returncode, 0, list_res.stderr)
        items = json.loads(list_res.stdout)
        self.assertTrue(any(item["path"].endswith("cli-wt") for item in items))

        # Test CLI worktree clean --dry-run
        clean_dry = self._run(self.repo, "worktree", "clean", "--dry-run")
        self.assertEqual(clean_dry.returncode, 0, clean_dry.stderr)
        self.assertIn("Dry run complete", clean_dry.stdout)
        self.assertTrue(wt_path.exists())

        # Test CLI worktree clean
        clean_res = self._run(self.repo, "worktree", "clean")
        self.assertEqual(clean_res.returncode, 0, clean_res.stderr)
        self.assertIn("Cleanup complete", clean_res.stdout)
        self.assertFalse(wt_path.exists())


if __name__ == "__main__":
    unittest.main()
