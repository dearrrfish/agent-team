from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

__base_version__ = "0.1.0"


def _read_baked_commit() -> str | None:
    try:
        import agent_team._version as v

        commit = getattr(v, "COMMIT_HASH", None)
        if commit:
            return str(commit).strip()
        archive_hash = getattr(v, "GIT_ARCHIVE_HASH", "")
        if archive_hash and not str(archive_hash).startswith("$Format:"):
            return str(archive_hash).strip()
    except (ImportError, AttributeError):
        return None
    return None


def get_commit_hash() -> str | None:
    env_commit = os.environ.get("AGENT_TEAM_COMMIT_HASH")
    if env_commit and env_commit.strip():
        raw = env_commit.strip()
        return raw[:7] if len(raw) == 40 else raw

    baked = _read_baked_commit()
    if baked:
        return baked

    if shutil.which("git"):
        try:
            repo_root = Path(__file__).resolve().parents[2]
            if (repo_root / ".git").exists():
                completed = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    cwd=repo_root,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if completed.returncode == 0:
                    val = completed.stdout.strip()
                    if val:
                        return val
        except OSError:
            return None

    return None


def get_version() -> str:
    commit = get_commit_hash()
    if commit:
        clean_commit = re.sub(r"[^a-zA-Z0-9.]+", ".", commit).strip(".")
        if clean_commit:
            return f"{__base_version__}+{clean_commit}"
    return __base_version__
