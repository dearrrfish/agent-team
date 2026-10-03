from __future__ import annotations

import io
import tempfile
import tomllib
import unittest
from importlib import resources
from pathlib import Path
from unittest.mock import patch

from agent_team.adapters import _mapped_role
from agent_team.cli import _effective_routing, _parser, main
from agent_team.config import load_roles, load_team_config, resolve_target_profile
from agent_team.config_editor import edit_roles
from agent_team.diagnostics import ValidationFailure
from agent_team.fs import atomic_write
from agent_team.models import ROLE_IDS


class ConfigRolesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / 'project'
        self.user = Path(self.directory.name) / 'user'
        self.root.mkdir()
        self.user.mkdir()
        (self.root / '.agent-team').mkdir()
        self.path = self.root / '.agent-team/team.toml'
        self.path.write_text('schema_version = 1\ninherit_user_defaults = false\n# retained comment\n')
        for module in ('config', 'config_editor'):
            user_patch = patch(f'agent_team.{module}.user_config_root', return_value=self.user)
            user_patch.start()
            self.addCleanup(user_patch.stop)
        for name in ('fetch_catalog', 'shutil.which'):
            prohibited = patch(f'agent_team.config_editor.{name}', side_effect=AssertionError('client discovery forbidden'))
            prohibited.start()
            self.addCleanup(prohibited.stop)
        self.output: list[str] = []

    def edit(self, answers: list[str], *, role: str | None = 'implementer', **kwargs: object) -> int:
        iterator = iter(answers)
        return edit_roles(self.root, role=role, target=kwargs.pop('target', 'codex'), read=lambda _: next(iterator), emit=self.output.append, **kwargs)

    def definitions(self) -> dict[str, object]:
        return {item.role_id: item for item in load_roles(load_team_config(self.root), self.root, target='codex')}

    def source_role(self, role_id: str = 'implementer', *, boundary: Path | None = None) -> Path:
        boundary = boundary or self.root
        directory = boundary / 'definitions' / role_id
        directory.mkdir(parents=True)
        base = resources.files('agent_team.assets').joinpath('definitions/roles', role_id)
        for name in ('role.toml', 'instructions.md'):
            (directory / name).write_text(base.joinpath(name).read_text())
        return directory

    def configure_source(self) -> Path:
        directory = self.source_role()
        self.path.write_text(self.path.read_text() + 'role_sources = ["builtin:roles", "definitions"]\n')
        return directory

    def test_cli_defaults_and_dispatch(self) -> None:
        args = _parser().parse_args(['config', 'roles'])
        self.assertEqual(args.scope, 'project')
        self.assertIsNone(args.role)
        self.assertFalse(args.dry_run)
        with patch('agent_team.cli.project_root', return_value=self.root), patch('agent_team.cli.edit_roles', return_value=0) as editor:
            self.assertEqual(main(['config', 'roles', '--role', 'ops', '--dry-run']), 0)
            editor.assert_called_once_with(self.root, scope='project', role='ops', target=None, dry_run=True)
        with patch('agent_team.cli.project_root', return_value=self.root), patch('agent_team.cli.edit_roles', return_value=0) as editor:
            self.assertEqual(main(['config', 'roles', '--target', 'codex,claude', '--role', 'ops']), 0)
            editor.assert_called_once_with(self.root, scope='project', role='ops', target='codex,claude', dry_run=False)
        with patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit):
            _parser().parse_args(['config', 'roles', '--role', 'custom-agent'])

    def test_single_role_pins_semantic_routing_without_clients(self) -> None:
        before = self.definitions()
        self.edit(['fast', 'low', 'yes'])
        data = tomllib.loads(self.path.read_text())
        self.assertEqual(data['roles'], {'implementer': {'targets': {'codex': {'model_class': 'fast', 'effort': 'low'}}}})
        self.assertIn('# retained comment', self.path.read_text())
        after = self.definitions()
        self.assertEqual(after['implementer'].model_class, 'fast')
        self.assertEqual(after['implementer'].effort, 'low')
        self.assertEqual(after['explorer'], before['explorer'])
        self.assertIn('source definition roles.implementer', '\n'.join(self.output))
        self.assertIn('--scope project --target codex --apply', self.output[-1])

    def test_default_visits_all_builtin_roles_in_order(self) -> None:
        self.edit(['deep', 'high'] * 6 + ['yes'], role=None)
        self.assertEqual(tuple(tomllib.loads(self.path.read_text())['roles']), ROLE_IDS)
        self.assertEqual(self.definitions()['coordinator'].routing_override_origins,
                         {'model_class': 'project', 'effort': 'project'})

    def test_enter_retains_absent_overlays(self) -> None:
        before = self.path.read_bytes()
        self.edit(['', ''])
        self.edit(['', ''], role='coordinator')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIn('keep coordinator preset', '\n'.join(self.output))
        self.assertFalse(self.definitions()['coordinator'].routing_override_origins)

    def test_explicit_equal_base_values_pin_coordinator(self) -> None:
        coordinator = self.definitions()['coordinator']
        self.edit([coordinator.model_class, coordinator.effort, 'yes'], role='coordinator')
        self.assertEqual(self.definitions()['coordinator'].routing_override_origins,
                         {'model_class': 'project', 'effort': 'project'})

    def test_enter_preserves_inherited_state_and_explicit_equal_pins_scope(self) -> None:
        self.path.write_text('schema_version = 1\n')
        user_path = self.user / 'team.toml'
        user_path.write_text('schema_version = 1\n[roles.implementer]\nmodel_class = "balanced"\neffort = "low"\n')
        before = user_path.read_bytes()
        self.edit(['', ''])
        self.assertNotIn('roles', tomllib.loads(self.path.read_text()))
        self.edit(['balanced', '', 'yes'])
        self.assertEqual(tomllib.loads(self.path.read_text())['roles']['implementer']['targets']['codex'], {'model_class': 'balanced'})
        role = self.definitions()['implementer']
        self.assertEqual(role.effort, 'low')
        self.assertEqual(role.routing_override_origins, {'model_class': 'project', 'effort': 'user'})
        self.assertEqual(user_path.read_bytes(), before)
        self.assertIn('user global routing overlay', '\n'.join(self.output))

    def test_user_scope_changes_only_user_config(self) -> None:
        user_path = self.user / 'team.toml'
        user_path.write_text('schema_version = 1\n')
        before = self.path.read_bytes()
        self.edit(['fast', '', 'yes'], scope='user')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(tomllib.loads(user_path.read_text())['roles']['implementer']['targets']['codex'], {'model_class': 'fast'})

    def test_empty_enabled_targets_omits_invalid_reinstall_command(self) -> None:
        self.path.write_text(self.path.read_text() + 'enabled_targets = []\n')
        self.edit(['fast', '', 'yes'])
        self.assertEqual(self.output[-1], 'Saved role routing.')
        self.assertNotIn('--target  --apply', '\n'.join(self.output))

    def test_default_targets_are_all_enabled_in_order(self) -> None:
        self.edit(['fast', '', 'balanced', '', 'deep', '', 'yes'], target=None)
        pins = tomllib.loads(self.path.read_text())['roles']['implementer']['targets']
        self.assertEqual(tuple(pins), ('codex', 'claude', 'antigravity'))
        self.assertEqual([pin['model_class'] for pin in pins.values()], ['fast', 'balanced', 'deep'])

    def test_multiple_targets_leave_unselected_routing_unchanged(self) -> None:
        self.path.write_text(self.path.read_text() + '\n[roles.implementer]\neffort = "medium"\n')
        self.edit(['fast', 'low', 'deep', '', 'yes'], target='codex,claude')
        config = load_team_config(self.root)
        roles = {name: {item.role_id: item for item in load_roles(config, self.root, target=name)}
                 for name in ('codex', 'claude', 'antigravity')}
        self.assertEqual(roles['codex']['implementer'].effort, 'low')
        self.assertEqual(roles['claude']['implementer'].model_class, 'deep')
        self.assertEqual(roles['antigravity']['implementer'].effort, 'medium')
        self.assertNotIn('antigravity', tomllib.loads(self.path.read_text())['roles']['implementer']['targets'])

    def test_invalid_targets_and_empty_default_fail(self) -> None:
        for target in ('', 'codex,', 'codex,codex', 'unknown'):
            with self.subTest(target=target), self.assertRaises(ValidationFailure):
                self.edit([], target=target)
        self.path.write_text(self.path.read_text() + 'enabled_targets = []\n')
        with self.assertRaisesRegex(ValidationFailure, 'no enabled targets'):
            self.edit([], target=None)

    def test_target_bound_user_leaf_wins_project_global_and_can_be_pinned(self) -> None:
        self.path.write_text('schema_version = 1\n[roles.implementer]\nmodel_class = "deep"\n')
        (self.user / 'team.toml').write_text('schema_version = 1\n[roles.implementer.targets.codex]\nmodel_class = "fast"\n')
        self.edit(['', ''])
        self.assertEqual(self.definitions()['implementer'].model_class, 'fast')
        self.edit(['fast', '', 'yes'])
        self.assertEqual(self.definitions()['implementer'].routing_override_origins['model_class'], 'project')

    def test_target_profile_changes_during_confirmation_are_detected(self) -> None:
        profile = self.root / 'codex.toml'
        profile.write_text(resources.files('agent_team.assets').joinpath('definitions/targets/codex.toml').read_text())
        self.path.write_text(self.path.read_text() + '\n[target_profiles]\ncodex = "codex.toml"\n')
        self.change_during_confirmation(lambda: profile.write_text(profile.read_text() + '# changed\n'))

    def test_models_show_target_binding_changes_only_bound_coordinator(self) -> None:
        self.path.write_text(self.path.read_text() + '\n[roles.coordinator.targets.codex]\nmodel_class = "deep"\neffort = "high"\n')
        args = _parser().parse_args(['models', 'show', '--format', 'json'])
        targets = _effective_routing(self.root, args)['targets']
        rows = {entry['target']: entry['roles'][0] for entry in targets}
        self.assertEqual(rows['codex']['model_class'], 'deep')
        self.assertEqual(rows['claude']['model_class'], 'coordinator')
        self.assertEqual(rows['antigravity']['model_class'], 'coordinator')
        for entry in targets:
            config = load_team_config(self.root)
            role = load_roles(config, self.root, target=entry['target'])[0]
            expected = _mapped_role(resolve_target_profile(config, entry['target'], self.root), 'balanced', role)
            self.assertEqual((entry['roles'][0]['native_model'], entry['roles'][0]['native_effort']), expected)

    def test_repeated_explicit_pin_is_noop(self) -> None:
        self.edit(['fast', 'low', 'yes'])
        before = self.path.read_bytes()
        self.edit(['fast', 'low'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.output[-1], 'No role routing changes.')

    def test_unrelated_config_and_source_files_preserved(self) -> None:
        directory = self.configure_source()
        self.path.write_text(self.path.read_text() + '\n[model_presets.codex.balanced]\ncoordinator_model = "unrelated"\n')
        snapshots = {path: path.read_bytes() for path in directory.iterdir()}
        self.edit(['fast', '', 'yes'])
        self.assertEqual(tomllib.loads(self.path.read_text())['model_presets']['codex']['balanced']['coordinator_model'], 'unrelated')
        for path, original in snapshots.items():
            self.assertEqual(path.read_bytes(), original)
        self.assertIn(str(directory / 'role.toml'), '\n'.join(self.output))

    def test_dry_run_decline_eof_and_interrupt(self) -> None:
        before = self.path.read_bytes()
        self.edit(['fast', 'low'], dry_run=True)
        self.assertIn('Dry run: no files saved.', self.output)
        for answer in ('', 'no', 'y'):
            self.edit(['fast', 'low', answer])
            self.assertEqual(self.path.read_bytes(), before)
        for error in (EOFError, KeyboardInterrupt):
            with patch('builtins.input', side_effect=error):
                self.assertEqual(edit_roles(self.root, role='implementer', emit=self.output.append), 0)
            self.assertEqual(self.path.read_bytes(), before)

    def test_missing_config_and_invalid_selection_do_not_initialize(self) -> None:
        for role in ('missing', 'custom-agent'):
            with self.assertRaises(ValidationFailure):
                self.edit([], role=role)
        self.path.unlink()
        with self.assertRaisesRegex(ValidationFailure, 'cannot read configuration'):
            self.edit([])
        self.assertFalse(self.path.exists())

    def test_custom_existing_role_overlay_is_preserved(self) -> None:
        directory = self.configure_source()
        custom = directory.with_name('custom-agent')
        custom.mkdir()
        (custom / 'role.toml').write_text((directory / 'role.toml').read_text().replace('id = "implementer"', 'id = "custom-agent"'))
        (custom / 'instructions.md').write_text('custom instructions')
        self.path.write_text(self.path.read_text() + '\n[roles.custom-agent]\neffort = "low"\n')
        self.edit(['fast', '', 'yes'])
        self.assertEqual(self.definitions()['custom-agent'].effort, 'low')
        self.assertEqual(self.definitions()['custom-agent'].instructions, 'custom instructions')

    def test_invalid_candidate_fails_before_preview(self) -> None:
        before = self.path.read_bytes()
        with patch('agent_team.config_editor.upsert_strings', return_value='schema_version = 1\n[roles.implementer]\neffort = "invalid"\n'), self.assertRaises(ValidationFailure):
            self.edit(['fast', 'low'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(any(line.startswith('---') for line in self.output))

    def test_invalid_profile_fails_before_preview(self) -> None:
        self.path.write_text(self.path.read_text() + '\n[target_profiles]\ncodex = "missing.toml"\n')
        before = self.path.read_bytes()
        with self.assertRaises(ValidationFailure):
            self.edit(['fast', 'low'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(any(line.startswith('---') for line in self.output))

    def change_during_confirmation(self, mutate: object) -> None:
        iterator = iter(['fast', 'low'])
        def read(prompt: str) -> str:
            if prompt.startswith('Save'):
                mutate()
                return 'yes'
            return next(iterator)
        with self.assertRaises(ValidationFailure):
            edit_roles(self.root, role='implementer', target='codex', read=read, emit=self.output.append)
        self.assertNotIn('roles', tomllib.loads(self.path.read_text()))

    def test_scoped_config_change_during_confirmation(self) -> None:
        self.change_during_confirmation(lambda: self.path.write_text(self.path.read_text() + '# external config edit\n'))
        self.assertIn('# external config edit', self.path.read_text())

    def test_role_definition_and_instructions_change_during_confirmation(self) -> None:
        directory = self.configure_source()
        for name in ('role.toml', 'instructions.md'):
            with self.subTest(name=name):
                dependency = directory / name
                self.change_during_confirmation(lambda path=dependency: path.write_text(path.read_text() + '\n# changed\n'))

    def test_role_inventory_addition_during_confirmation(self) -> None:
        self.configure_source()
        self.change_during_confirmation(lambda: self.source_role('explorer'))

    def test_source_resolution_change_during_confirmation(self) -> None:
        directory = self.configure_source()
        alternate = self.root / 'alternative'
        alternate.mkdir()
        target = alternate / 'implementer'
        target.mkdir()
        for name in ('role.toml', 'instructions.md'):
            (target / name).write_bytes((directory / name).read_bytes())
        def swap() -> None:
            source = self.root / 'definitions'
            source.rename(self.root / 'original-definitions')
            source.symlink_to(alternate, target_is_directory=True)
        self.change_during_confirmation(swap)

    def test_new_inherited_config_detected(self) -> None:
        self.path.write_text('schema_version = 1\n')
        self.change_during_confirmation(lambda: (self.user / 'team.toml').write_text('schema_version = 1\n[roles.implementer]\neffort = "high"\n'))

    def test_symlink_scoped_destination_rejected(self) -> None:
        destination = self.root / 'original.toml'
        destination.write_bytes(self.path.read_bytes())
        self.path.unlink()
        self.path.symlink_to(destination)
        with self.assertRaisesRegex(ValidationFailure, 'symlink'):
            self.edit([])
        self.assertNotIn('roles', tomllib.loads(destination.read_text()))

    def test_replacement_interrupt_recovers_and_reports_save_failure(self) -> None:
        before = self.path.read_bytes()
        def write(path: Path, content: str) -> None:
            atomic_write(path, content)
            if content != before.decode():
                raise KeyboardInterrupt
        with patch('agent_team.config_editor.atomic_write', side_effect=write), self.assertRaisesRegex(ValidationFailure, 'earlier writes restored'):
            self.edit(['fast', 'low', 'yes'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertNotIn('Cancelled: no files saved.', self.output)

    def test_models_show_follows_coordinator_field_presence_independently(self) -> None:
        base = self.path.read_text() + '''\n[model_presets.codex.balanced]\ncoordinator_model = "dedicated"\ncoordinator_effort = "medium"\n[model_presets.codex.balanced.models]\ndeep = "class-model"\n[model_presets.codex.balanced.effort]\nhigh = "high"\n'''
        for class_present, effort_present in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(model=class_present, effort=effort_present):
                overlay = '\n[roles.coordinator]\n'
                overlay += 'model_class = "deep"\n' if class_present else ''
                overlay += 'effort = "high"\n' if effort_present else ''
                self.path.write_text(base + overlay)
                args = _parser().parse_args(['models', 'show', '--target', 'codex', '--format', 'json'])
                row = _effective_routing(self.root, args)['targets'][0]['roles'][0]
                config = load_team_config(self.root)
                coordinator = load_roles(config, self.root)[0]
                self.assertEqual((row['native_model'], row['native_effort']),
                                 _mapped_role(resolve_target_profile(config, 'codex', self.root), 'balanced', coordinator))
                self.assertEqual(row['model_class'], 'deep' if class_present else 'coordinator')
                self.assertEqual(row['model_source'], 'model_presets.codex.balanced.models.deep' if class_present else 'model_presets.codex.balanced.coordinator_model')
                self.assertEqual(row['effort_source'], 'model_presets.codex.balanced.effort.high' if effort_present else 'model_presets.codex.balanced.coordinator_effort')


if __name__ == '__main__':
    unittest.main()
