import re
import tomllib
import unittest
from pathlib import Path

from agent_team import __version__

ROOT = Path(__file__).parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_release_version_is_consistent(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project_version = project["project"]["version"]
        self.assertEqual(project_version, __version__)

        flake = (ROOT / "flake.nix").read_text(encoding="utf-8")
        match = re.search(r'^\s*version = "([^"]+)";', flake, re.MULTILINE)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.group(1), __version__)

        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [{__version__}]", changelog)
        release_notes = (
            ROOT / "docs" / "releases" / f"v{__version__}.md"
        ).read_text(encoding="utf-8")
        self.assertTrue(release_notes.startswith(f"# agent-team v{__version__}\n"))


if __name__ == "__main__":
    unittest.main()
