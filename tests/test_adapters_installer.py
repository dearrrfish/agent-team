import json
import tempfile
import tomllib
import unittest
from pathlib import Path, PurePosixPath

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
            coordination_skill = codex[next(
                path for path in codex if str(path).endswith("team-coordinate/SKILL.md")
            )]
            self.assertEqual(explorer["model"], "gpt-5.6-luna")
            self.assertEqual(explorer["sandbox_mode"], "read-only")
            self.assertEqual(coordinator["model"], "gpt-5.6-sol")
            self.assertEqual(coordinator["model_reasoning_effort"], "medium")
            self.assertIn("Name the native custom-agent role explicitly", coordination_skill)
            self.assertIn("confirm the project is trusted", coordination_skill)
            self.assertIn("do not silently spawn a generic agent", coordination_skill)
            self.assertIn("read `max_workers`", coordination_skill)
            self.assertIn("Team tier always requires reports", coordination_skill)
            self.assertIn("`--run <slug>`", coordination_skill)
            self.assertIn("all of its dependencies", coordination_skill)
            self.assertIn("omit shell access from native read-only roles", coordination_skill)
            self.assertIn("replacing its task and role placeholders", coordination_skill)

            review_skill = codex[next(
                path for path in codex if str(path).endswith("team-review/SKILL.md")
            )]
            self.assertIn("Increment `review.used`", review_skill)

            quality_codex = render_target("codex", config, root, "quality")
            quality_coordinator = tomllib.loads(quality_codex[next(
                path for path in quality_codex if str(path).endswith("coordinator.toml")
            )])
            self.assertEqual(quality_coordinator["model"], "gpt-6-astra")
            self.assertIn("Use when:", coordinator["description"])
            self.assertIn("Avoid when:", coordinator["description"])
            self.assertIn("within at most 64 turns", coordinator["developer_instructions"])
            self.assertIn("`agent-report` report contract", coordinator["developer_instructions"])
            self.assertIn("supports worktree isolation", coordinator["developer_instructions"])
            self.assertIn("Delegate only bounded work", coordinator["developer_instructions"])
            self.assertNotIn("Do not delegate to another agent", coordinator["developer_instructions"])

            claude = render_target("claude", config, root)
            claude_explorer = claude[next(path for path in claude if str(path).endswith("explorer.md"))]
            claude_coordinator = claude[next(
                path for path in claude if str(path).endswith("coordinator.md")
            )]
            self.assertNotIn("effort:", claude_explorer)
            self.assertIn("permissionMode: plan", claude_explorer)
            self.assertIn("maxTurns: 16", claude_explorer)
            self.assertNotIn("Bash", claude_explorer)
            self.assertIn("tools: Read, Glob, Grep, WebFetch, WebSearch", claude_explorer)
            self.assertIn("Agent", claude_coordinator)
            self.assertIn("Bash", claude_coordinator)
            self.assertIn(
                "tools: Read, Glob, Grep, Edit, Write, Bash, WebFetch, WebSearch, Agent",
                claude_coordinator,
            )

            antigravity = render_target("antigravity", config, root)
            self.assertTrue(any(str(path) == ".agents/agents/reviewer/agent.md" for path in antigravity))
            antigravity_coordinator = antigravity[next(
                path for path in antigravity if str(path).endswith("coordinator/agent.md")
            )]
            antigravity_explorer = antigravity[next(
                path for path in antigravity if str(path).endswith("explorer/agent.md")
            )]
            self.assertIn("Antigravity supports worktree isolation", antigravity_coordinator)
            self.assertIn("`branch` workspace option", antigravity_coordinator)
            self.assertIn('"invoke_subagent"', antigravity_coordinator)
            self.assertIn('"view_file"', antigravity_explorer)
            self.assertNotIn('"run_command"', antigravity_explorer)
            self.assertIn('"search_web"', antigravity_explorer)
            self.assertNotIn('"read"', antigravity_explorer)
            self.assertNotIn('"shell"', antigravity_explorer)
            self.assertIn('"run_command"', antigravity_coordinator)

            antigravity_user = render_target("antigravity", config, root, scope="user")
            self.assertTrue(any(
                str(path) == ".gemini/config/agents/reviewer/agent.md"
                for path in antigravity_user
            ))
            self.assertTrue(any(
                str(path) == ".gemini/antigravity-cli/skills/team-review/SKILL.md"
                for path in antigravity_user
            ))

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

    def test_render_preflights_all_conflicts_before_writing(self) -> None:
        with self._project() as directory, tempfile.TemporaryDirectory() as output_directory:
            root = Path(directory)
            output = Path(output_directory)
            config = load_team_config(root)
            files = render_target("codex", config, root)
            ordered = list(files)
            conflict = output / Path(ordered[-1])
            conflict.parent.mkdir(parents=True)
            conflict.write_text("user content", encoding="utf-8")

            with self.assertRaises(ValidationFailure):
                write_rendered(output, files)

            self.assertFalse((output / Path(ordered[0])).exists())
            self.assertEqual(conflict.read_text(encoding="utf-8"), "user content")

    def test_render_and_install_preflight_non_directory_parents(self) -> None:
        files = {
            PurePosixPath("a.txt"): "generated",
            PurePosixPath("z/child.txt"): "generated",
        }
        for operation in ("render", "install"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "z").write_text("parent blocker", encoding="utf-8")
                with self.assertRaises(ValidationFailure) as context:
                    if operation == "render":
                        write_rendered(root, files)
                    else:
                        install_files(
                            target="codex", target_root=root, files=files,
                            apply=True, force=False, backups=True,
                        )
                self.assertTrue(any(item.code == "parent" for item in context.exception.diagnostics))
                self.assertFalse((root / "a.txt").exists())
                self.assertEqual((root / "z").read_text(encoding="utf-8"), "parent blocker")

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
            state_path = target_root / ".agent-team" / "install-state.json"
            initial_state = state_path.read_bytes()
            initial_mtime = state_path.stat().st_mtime_ns
            second = install_files(
                target="codex", target_root=target_root, files=files,
                apply=False, force=False, backups=True,
            )
            self.assertTrue(all(action.action == "unchanged" for action in second))
            applied_second = install_files(
                target="codex", target_root=target_root, files=files,
                apply=True, force=False, backups=True,
            )
            self.assertTrue(all(action.action == "unchanged" for action in applied_second))
            self.assertEqual(state_path.read_bytes(), initial_state)
            self.assertEqual(state_path.stat().st_mtime_ns, initial_mtime)

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
            forced_state = json.loads(state_path.read_text(encoding="utf-8"))
            backup_reference = forced_state["files"][relative.as_posix()]["backup"]
            self.assertIsInstance(backup_reference, str)
            install_files(
                target="codex", target_root=target_root, files=files,
                apply=True, force=False, backups=True,
            )
            unchanged_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                unchanged_state["files"][relative.as_posix()]["backup"],
                backup_reference,
            )

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

    def test_install_surfaces_but_retains_stale_managed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as target_directory:
            target_root = Path(target_directory)
            initial = {
                PurePosixPath("agents/active.md"): "active",
                PurePosixPath("agents/obsolete.md"): "obsolete",
            }
            install_files(
                target="codex", target_root=target_root, files=initial,
                apply=True, force=False, backups=True,
            )
            current = {PurePosixPath("agents/active.md"): "active"}
            preview = install_files(
                target="codex", target_root=target_root, files=current,
                apply=False, force=False, backups=True,
            )
            self.assertTrue(any(
                action.path == "agents/obsolete.md" and action.action == "stale"
                for action in preview
            ))
            install_files(
                target="codex", target_root=target_root, files=current,
                apply=True, force=False, backups=True,
            )
            self.assertEqual(
                (target_root / "agents" / "obsolete.md").read_text(encoding="utf-8"),
                "obsolete",
            )

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
