import tempfile
import tomllib
import unittest
from pathlib import Path

from agent_team.adapters import render_target, write_rendered
from agent_team.config import DEFAULT_TEAM_TOML, load_team_config
from agent_team.diagnostics import ValidationFailure
from agent_team.installer import install_files


class AdapterAndInstallerTests(unittest.TestCase):
    def _project(self) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / ".agent-team").mkdir()
        (root / ".agent-team" / "team.toml").write_text(DEFAULT_TEAM_TOML, encoding="utf-8")
        return temporary

    def test_all_targets_render_deterministically(self) -> None:
        with self._project() as directory:
            root = Path(directory)
            config = load_team_config(root)
            for target in ("codex", "claude", "antigravity"):
                first = render_target(target, config, root)
                second = render_target(target, config, root)
                self.assertEqual(first, second)
                self.assertEqual(len(first), 10)

            codex = render_target("codex", config, root)
            explorer = tomllib.loads(codex[next(path for path in codex if str(path).endswith("explorer.toml"))])
            coordinator = tomllib.loads(codex[next(path for path in codex if str(path).endswith("coordinator.toml"))])
            self.assertEqual(explorer["model"], "gpt-5.6-luna")
            self.assertEqual(explorer["sandbox_mode"], "read-only")
            self.assertEqual(coordinator["model"], "gpt-5.6-sol")
            self.assertEqual(coordinator["model_reasoning_effort"], "medium")

            claude = render_target("claude", config, root)
            claude_explorer = claude[next(path for path in claude if str(path).endswith("explorer.md"))]
            self.assertNotIn("effort:", claude_explorer)
            self.assertIn("permissionMode: plan", claude_explorer)

            antigravity = render_target("antigravity", config, root)
            self.assertTrue(any(str(path) == ".agents/agents/reviewer/agent.md" for path in antigravity))

    def test_render_refuses_changed_existing_output(self) -> None:
        with self._project() as directory, tempfile.TemporaryDirectory() as output_directory:
            root = Path(directory)
            output = Path(output_directory)
            config = load_team_config(root)
            files = render_target("codex", config, root)
            written = write_rendered(output, files)
            self.assertEqual(len(written), 10)
            write_rendered(output, files)
            written[0].write_text("changed", encoding="utf-8")
            with self.assertRaises(ValidationFailure):
                write_rendered(output, files)

    def test_install_preview_apply_idempotence_drift_and_backup(self) -> None:
        with self._project() as directory, tempfile.TemporaryDirectory() as target_directory:
            root = Path(directory)
            target_root = Path(target_directory)
            config = load_team_config(root)
            files = render_target("codex", config, root)

            preview = install_files(
                target="codex", target_root=target_root, files=files,
                apply=False, force=False, backups=True,
            )
            self.assertTrue(all(action.action == "create" for action in preview))
            self.assertFalse((target_root / ".agent-team" / "install-state.json").exists())

            install_files(
                target="codex", target_root=target_root, files=files,
                apply=True, force=False, backups=True,
            )
            second = install_files(
                target="codex", target_root=target_root, files=files,
                apply=False, force=False, backups=True,
            )
            self.assertTrue(all(action.action == "unchanged" for action in second))

            relative = next(iter(files))
            changed = target_root / Path(relative)
            changed.write_text("local drift", encoding="utf-8")
            with self.assertRaises(ValidationFailure):
                install_files(
                    target="codex", target_root=target_root, files=files,
                    apply=False, force=False, backups=True,
                )
            install_files(
                target="codex", target_root=target_root, files=files,
                apply=True, force=True, backups=True,
            )
            self.assertEqual(changed.read_text(encoding="utf-8"), files[relative])
            backups = list((target_root / ".agent-team" / "backups").rglob(changed.name))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "local drift")

    def test_unmanaged_conflict_is_refused(self) -> None:
        with self._project() as directory, tempfile.TemporaryDirectory() as target_directory:
            root = Path(directory)
            target_root = Path(target_directory)
            config = load_team_config(root)
            files = render_target("claude", config, root)
            relative = next(iter(files))
            existing = target_root / Path(relative)
            existing.parent.mkdir(parents=True)
            existing.write_text("user content", encoding="utf-8")
            with self.assertRaises(ValidationFailure) as context:
                install_files(
                    target="claude", target_root=target_root, files=files,
                    apply=True, force=False, backups=True,
                )
            self.assertTrue(any(item.code == "conflict" for item in context.exception.diagnostics))
            self.assertEqual(existing.read_text(encoding="utf-8"), "user content")

    def test_directory_destination_and_backup_disabled_fail_before_writes(self) -> None:
        with self._project() as directory, tempfile.TemporaryDirectory() as target_directory:
            root = Path(directory)
            target_root = Path(target_directory)
            config = load_team_config(root)
            files = render_target("codex", config, root)
            relative = next(iter(files))
            destination = target_root / Path(relative)
            destination.mkdir(parents=True)
            with self.assertRaises(ValidationFailure) as context:
                install_files(
                    target="codex", target_root=target_root, files=files,
                    apply=True, force=True, backups=True,
                )
            self.assertTrue(any(item.code == "directory" for item in context.exception.diagnostics))
            self.assertFalse((target_root / ".agent-team" / "install-state.json").exists())

        with self._project() as directory, tempfile.TemporaryDirectory() as target_directory:
            root = Path(directory)
            target_root = Path(target_directory)
            config = load_team_config(root)
            files = render_target("codex", config, root)
            relative = next(iter(files))
            destination = target_root / Path(relative)
            destination.parent.mkdir(parents=True)
            destination.write_text("unmanaged", encoding="utf-8")
            with self.assertRaises(ValidationFailure) as context:
                install_files(
                    target="codex", target_root=target_root, files=files,
                    apply=True, force=True, backups=False,
                )
            self.assertTrue(any(item.code == "backup" for item in context.exception.diagnostics))
            self.assertFalse((target_root / ".agent-team" / "install-state.json").exists())


if __name__ == "__main__":
    unittest.main()
