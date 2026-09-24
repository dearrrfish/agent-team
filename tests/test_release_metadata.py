import re
import tomllib
import unittest
from pathlib import Path

from agent_team import __base_version__, __version__

ROOT = Path(__file__).parents[1]
CANONICAL_REPOSITORY = "https://github.com/dearrrfish/agent-team"


class ReleaseMetadataTests(unittest.TestCase):
    def test_release_version_is_consistent(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project_version = project["project"]["version"]
        self.assertEqual(project_version, __base_version__)

        flake = (ROOT / "flake.nix").read_text(encoding="utf-8")
        match = re.search(r'^\s*version = "([^"]+)";', flake, re.MULTILINE)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.group(1), __base_version__)

        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [{__base_version__}]", changelog)
        release_notes = (
            ROOT / "docs" / "releases" / f"v{__base_version__}.md"
        ).read_text(encoding="utf-8")
        self.assertTrue(release_notes.startswith(f"# agent-team v{__base_version__}\n"))

        changelog_date = re.search(
            rf"^## \[{re.escape(__base_version__)}\] - (\d{{4}}-\d{{2}}-\d{{2}})$",
            changelog,
            re.MULTILINE,
        )
        release_date = re.search(
            r"^Release date: (\d{4}-\d{2}-\d{2})$", release_notes, re.MULTILINE
        )
        self.assertIsNotNone(changelog_date)
        self.assertIsNotNone(release_date)
        assert changelog_date is not None
        assert release_date is not None
        self.assertEqual(changelog_date.group(1), release_date.group(1))
        self.assertIn(
            f"[{__base_version__}]: {CANONICAL_REPOSITORY}/releases/tag/v{__base_version__}",
            changelog,
        )

    def test_version_format(self) -> None:
        self.assertRegex(
            __version__, rf"^{re.escape(__base_version__)}(\+[0-9a-zA-Z.]+)?$"
        )

    def test_canonical_repository_metadata_is_consistent(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        urls = project["project"]["urls"]
        self.assertEqual(urls["Homepage"], CANONICAL_REPOSITORY)
        self.assertEqual(urls["Repository"], f"{CANONICAL_REPOSITORY}.git")
        self.assertEqual(urls["Issues"], f"{CANONICAL_REPOSITORY}/issues")
        self.assertEqual(
            urls["Changelog"], f"{CANONICAL_REPOSITORY}/blob/main/CHANGELOG.md"
        )

        flake = (ROOT / "flake.nix").read_text(encoding="utf-8")
        self.assertIn(f'homepage = "{CANONICAL_REPOSITORY}";', flake)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("nix run github:dearrrfish/agent-team -- --version", readme)


if __name__ == "__main__":
    unittest.main()
