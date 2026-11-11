"""Git worktree discovery, status inspection, evidence preservation, and safe cleanup."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class WorktreeStatus(str, Enum):
    CLEAN_MERGED = "CLEAN_MERGED"
    AHEAD = "AHEAD"
    DIRTY = "DIRTY"
    PRUNABLE = "PRUNABLE"
    LOCKED = "LOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class WorktreeInfo:
    path: Path
    branch: str | None
    head_commit: str | None
    is_main: bool
    is_prunable: bool
    is_locked: bool
    status: WorktreeStatus
    details: str = ""
    associated_slug: str | None = None


@dataclass
class CleanResult:
    path: Path
    success: bool
    action: str
    details: str
    synced_files: list[Path] = field(default_factory=list)


def _run_git(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    cmd = ["git"] + args
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return res.returncode, res.stdout.strip(), res.stderr.strip()


def get_base_branch(repo_path: Path) -> str:
    """Detect default/base branch for repository (e.g. main or master)."""
    code, stdout, _ = _run_git(["symbolic-ref", "--short", "HEAD"], cwd=repo_path)
    if code == 0 and stdout:
        return stdout
    # Fallback to main or master
    code, stdout, _ = _run_git(["rev-parse", "--verify", "main"], cwd=repo_path)
    if code == 0:
        return "main"
    return "master"


def detect_associated_slug(
    worktree_path: Path, branch: str | None, repo_path: Path | None = None
) -> str | None:
    """Attempt to detect the associated agent-team run slug."""
    # Check if run artifacts exist in .agent-team/runs/ inside the worktree
    runs_dir = worktree_path / ".agent-team" / "runs"
    if runs_dir.is_dir():
        slugs = [d.name for d in runs_dir.iterdir() if d.is_dir()]
        if len(slugs) == 1:
            return slugs[0]

    # Check branch name e.g. agent-team/<slug>/<task>
    if branch and branch.startswith("agent-team/"):
        parts = branch.split("/")
        if len(parts) >= 2:
            return parts[1]

    # Check if directory name matches an existing run in main repo
    name = worktree_path.name
    if repo_path:
        repo_runs = repo_path / ".agent-team" / "runs"
        if repo_runs.is_dir():
            if (repo_runs / name).is_dir():
                return name
            if "-" in name:
                prefix = name.rsplit("-", 1)[0]
                if (repo_runs / prefix).is_dir():
                    return prefix

    return None


def list_worktrees(repo_path: Path, base_branch: str | None = None) -> list[WorktreeInfo]:
    """Inspect and return all worktrees in the repository with status."""
    if base_branch is None:
        base_branch = get_base_branch(repo_path)

    code, stdout, stderr = _run_git(["worktree", "list", "--porcelain"], cwd=repo_path)
    if code != 0:
        return []

    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in stdout.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        parts = line.split(" ", 1)
        key = parts[0]
        val = parts[1] if len(parts) > 1 else ""
        current[key] = val
    if current:
        entries.append(current)

    worktrees: list[WorktreeInfo] = []
    main_repo_resolved = repo_path.resolve()

    for idx, entry in enumerate(entries):
        raw_path = entry.get("worktree", "")
        if not raw_path:
            continue
        wt_path = Path(raw_path)
        is_main = idx == 0 or (wt_path.resolve() == main_repo_resolved)
        branch_ref = entry.get("branch", "")
        branch = branch_ref.removeprefix("refs/heads/") if branch_ref else None
        head = entry.get("HEAD")
        is_prunable = "prunable" in entry or not wt_path.exists()
        is_locked = "locked" in entry

        associated_slug = None if is_main else detect_associated_slug(wt_path, branch, repo_path=repo_path)

        if is_main:
            status = WorktreeStatus.CLEAN_MERGED
            details = "main working tree"
        elif is_prunable:
            status = WorktreeStatus.PRUNABLE
            details = entry.get("prunable") or "worktree path does not exist on disk"
        elif is_locked:
            status = WorktreeStatus.LOCKED
            details = entry.get("locked") or "locked worktree"
        else:
            # Check dirty status
            st_code, st_out, _ = _run_git(["status", "--porcelain"], cwd=wt_path)
            if st_code == 0 and st_out:
                lines = [line for line in st_out.splitlines() if line.strip()]
                status = WorktreeStatus.DIRTY
                details = f"{len(lines)} uncommitted file(s)"
            elif st_code != 0:
                status = WorktreeStatus.UNKNOWN
                details = "failed to inspect worktree status"
            else:
                # Clean on disk, check if merged to base_branch
                if branch and branch != base_branch:
                    log_code, log_out, _ = _run_git(
                        ["log", f"{base_branch}..{branch}", "--oneline"], cwd=repo_path
                    )
                    if log_code == 0 and log_out.strip():
                        commit_count = len(log_out.strip().splitlines())
                        status = WorktreeStatus.AHEAD
                        details = f"{commit_count} unmerged commit(s) ahead of {base_branch}"
                    else:
                        status = WorktreeStatus.CLEAN_MERGED
                        details = f"clean and merged into {base_branch}"
                elif branch == base_branch:
                    status = WorktreeStatus.CLEAN_MERGED
                    details = f"tracking {base_branch}"
                elif head:
                    # Detached HEAD
                    anc_code, _, _ = _run_git(
                        ["merge-base", "--is-ancestor", head, base_branch], cwd=repo_path
                    )
                    if anc_code == 0:
                        status = WorktreeStatus.CLEAN_MERGED
                        details = f"detached HEAD commit merged into {base_branch}"
                    else:
                        status = WorktreeStatus.AHEAD
                        details = f"detached HEAD commit not in {base_branch}"
                else:
                    status = WorktreeStatus.CLEAN_MERGED
                    details = "clean"

        worktrees.append(WorktreeInfo(
            path=wt_path,
            branch=branch,
            head_commit=head,
            is_main=is_main,
            is_prunable=is_prunable,
            is_locked=is_locked,
            status=status,
            details=details,
            associated_slug=associated_slug,
        ))

    return worktrees


def sync_run_artifacts(
    worktree_path: Path, main_repo_path: Path, slug: str | None = None
) -> list[Path]:
    """Safely synchronize .agent-team/runs artifacts from a worktree back to the main repository."""
    synced: list[Path] = []
    wt_runs = worktree_path / ".agent-team" / "runs"
    if not wt_runs.is_dir():
        return synced

    main_runs = main_repo_path / ".agent-team" / "runs"
    main_runs.mkdir(parents=True, exist_ok=True)

    for run_dir in wt_runs.iterdir():
        if not run_dir.is_dir():
            continue
        if slug and run_dir.name != slug:
            continue
        dest_run_dir = main_runs / run_dir.name
        dest_run_dir.mkdir(parents=True, exist_ok=True)

        for root, _, files in os.walk(run_dir):
            rel_dir = Path(root).relative_to(run_dir)
            target_sub_dir = dest_run_dir / rel_dir
            target_sub_dir.mkdir(parents=True, exist_ok=True)
            for f in files:
                src_file = Path(root) / f
                dest_file = target_sub_dir / f
                if not dest_file.exists() or src_file.stat().st_mtime >= dest_file.stat().st_mtime:
                    shutil.copy2(src_file, dest_file)
                    synced.append(dest_file)

    return synced


def clean_worktree(
    repo_path: Path,
    info: WorktreeInfo,
    *,
    force: bool = False,
    discard_changes: bool = False,
    sync_artifacts: bool = True,
    dry_run: bool = False,
) -> CleanResult:
    """Safely remove a single worktree adhering to the safety policy."""
    if info.is_main:
        return CleanResult(
            path=info.path,
            success=False,
            action="skipped",
            details="cannot remove main worktree",
        )

    # Check safety boundaries
    if info.status == WorktreeStatus.DIRTY and not discard_changes:
        return CleanResult(
            path=info.path,
            success=False,
            action="blocked",
            details=f"worktree has uncommitted changes: {info.details} (use --discard-changes to force)",
        )

    if info.status == WorktreeStatus.AHEAD and not force:
        return CleanResult(
            path=info.path,
            success=False,
            action="blocked",
            details=f"worktree has unmerged commits: {info.details} (use --force to force)",
        )

    if info.status == WorktreeStatus.LOCKED and not force:
        return CleanResult(
            path=info.path,
            success=False,
            action="blocked",
            details=f"worktree is locked: {info.details} (use --force to unlock)",
        )

    synced: list[Path] = []
    if sync_artifacts and info.path.exists():
        synced = sync_run_artifacts(info.path, repo_path, slug=info.associated_slug)

    if dry_run:
        return CleanResult(
            path=info.path,
            success=True,
            action="would-remove",
            details=f"would clean {info.status.value} worktree (artifacts to sync: {len(synced)})",
            synced_files=synced,
        )

    # Prunable / missing directory: prune metadata directly
    if info.is_prunable or not info.path.exists():
        p_code, _, p_err = _run_git(["worktree", "prune"], cwd=repo_path)
        if p_code == 0:
            return CleanResult(
                path=info.path,
                success=True,
                action="pruned",
                details="pruned orphaned worktree metadata",
                synced_files=synced,
            )
        return CleanResult(
            path=info.path,
            success=False,
            action="failed",
            details=f"git worktree prune failed: {p_err}",
        )

    # Unlock if locked and force
    if info.is_locked and force:
        _run_git(["worktree", "unlock", str(info.path)], cwd=repo_path)

    # Perform git worktree remove
    remove_args = ["worktree", "remove"]
    if force or discard_changes:
        remove_args.append("--force")
    remove_args.append(str(info.path))

    rem_code, _, rem_err = _run_git(remove_args, cwd=repo_path)
    if rem_code != 0:
        return CleanResult(
            path=info.path,
            success=False,
            action="failed",
            details=f"git worktree remove failed: {rem_err}",
            synced_files=synced,
        )

    # Always prune after removal
    _run_git(["worktree", "prune"], cwd=repo_path)

    return CleanResult(
        path=info.path,
        success=True,
        action="removed",
        details="worktree safely removed and pruned",
        synced_files=synced,
    )
