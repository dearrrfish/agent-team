from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agent_team.version import (
    __base_version__,
    _read_baked_commit,
    get_commit_hash,
    get_version,
)


class VersionTests(unittest.TestCase):
    def test_base_version(self) -> None:
        self.assertEqual(__base_version__, "0.1.0")

    def test_get_commit_hash_from_env(self) -> None:
        with (
            patch.dict(os.environ, {"AGENT_TEAM_COMMIT_HASH": "1234567"}),
            patch("agent_team.version._read_baked_commit", return_value=None),
        ):
            self.assertEqual(get_commit_hash(), "1234567")

    def test_get_commit_hash_from_env_full_sha_truncated(self) -> None:
        full_sha = "4110792eb9473009cf8d674c7aeb1b1035a7ff24"
        with (
            patch.dict(os.environ, {"AGENT_TEAM_COMMIT_HASH": full_sha}),
            patch("agent_team.version._read_baked_commit", return_value=None),
        ):
            self.assertEqual(get_commit_hash(), "4110792")

    def test_get_commit_hash_from_baked(self) -> None:
        with (
            patch.dict(os.environ, {"AGENT_TEAM_COMMIT_HASH": ""}),
            patch("agent_team.version._read_baked_commit", return_value="fedcba9"),
        ):
            self.assertEqual(get_commit_hash(), "fedcba9")

    def test_get_commit_hash_none_when_unavailable(self) -> None:
        with (
            patch.dict(os.environ, {"AGENT_TEAM_COMMIT_HASH": ""}),
            patch("agent_team.version._read_baked_commit", return_value=None),
            patch("shutil.which", return_value=None),
        ):
            self.assertIsNone(get_commit_hash())

    def test_get_version_with_commit(self) -> None:
        with patch("agent_team.version.get_commit_hash", return_value="4110792"):
            self.assertEqual(get_version(), "0.1.0+4110792")

    def test_get_version_normalizes_pep440(self) -> None:
        # Dash in dirty version should be replaced by dot
        with patch("agent_team.version.get_commit_hash", return_value="4110792-dirty"):
            self.assertEqual(get_version(), "0.1.0+4110792.dirty")

    def test_get_version_without_commit(self) -> None:
        with patch("agent_team.version.get_commit_hash", return_value=None):
            self.assertEqual(get_version(), "0.1.0")

    def test_read_baked_commit_handles_format_placeholder(self) -> None:
        with (
            patch("agent_team._version.COMMIT_HASH", None, create=True),
            patch(
                "agent_team._version.GIT_ARCHIVE_HASH",
                "$Format:%h$",
                create=True,
            ),
        ):
            self.assertIsNone(_read_baked_commit())

    def test_read_baked_commit_reads_expanded_archive_placeholder(self) -> None:
        with (
            patch("agent_team._version.COMMIT_HASH", None, create=True),
            patch(
                "agent_team._version.GIT_ARCHIVE_HASH", "9876543", create=True
            ),
        ):
            self.assertEqual(_read_baked_commit(), "9876543")


if __name__ == "__main__":
    unittest.main()
