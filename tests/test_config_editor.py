from __future__ import annotations

import io
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from importlib import resources
from pathlib import Path
from unittest.mock import patch

from agent_team.catalog import CatalogResult
from agent_team.cli import _parser, main
from agent_team.config import load_team_config, load_user_config, resolve_target_profile
from agent_team.config_editor import (
    Candidate,
    apply_candidates,
    edit_model_presets,
    select_targets,
)
from agent_team.diagnostics import ValidationFailure
from agent_team.fs import atomic_write


class ConfigEditorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / 'project'
        self.user = Path(self.directory.name) / 'user'
        self.root.mkdir()
        self.user.mkdir()
        (self.root / '.agent-team').mkdir()
        self.path = self.root / '.agent-team' / 'team.toml'
        self.path.write_text('schema_version = 1\ninherit_user_defaults = false\n# keep comment\n')
        self.user_patch = patch('agent_team.config.user_config_root', return_value=self.user)
        self.user_patch.start()
        self.addCleanup(self.user_patch.stop)
        self.editor_user_patch = patch('agent_team.config_editor.user_config_root', return_value=self.user)
        self.editor_user_patch.start()
        self.addCleanup(self.editor_user_patch.stop)
        self.which = patch('agent_team.config_editor.shutil.which', return_value='/client')
        self.which.start()
        self.addCleanup(self.which.stop)
        self.catalog = CatalogResult('codex', 'test', 'ok', tuple(
            {'model_id': model, 'display_name': model, 'effort_options': ['low', 'medium', 'high', 'xhigh']}
            for model in ('new', 'gpt-6-luna', 'gpt-5.6-terra', 'gpt-6-sol', 'gpt-6-astra')
        ))
        self.fetch = patch('agent_team.config_editor.fetch_catalog', return_value=self.catalog)
        self.fetch.start()
        self.addCleanup(self.fetch.stop)
        self.output: list[str] = []

    def edit(self, answers: list[str], **kwargs: object) -> int:
        iterator = iter(answers)
        return edit_model_presets(self.root, target='codex', preset='balanced',
                                  read=lambda _: next(iterator), emit=self.output.append, **kwargs)

    def routing(self, preset: str = 'balanced') -> object:
        return resolve_target_profile(load_team_config(self.root), 'codex', self.root).presets[preset]

    def file_profile(self, inherited: bool = False) -> Path:
        text = resources.files('agent_team.assets').joinpath('definitions/targets/codex.toml').read_text()
        boundary = self.user if inherited else self.root
        path = boundary / 'codex.toml'
        path.write_text('# profile comment\n' + text)
        config_path = self.user / 'team.toml' if inherited else self.path
        config_path.write_text('schema_version = 1\n[target_profiles]\ncodex = "codex.toml"\n')
        if inherited:
            self.path.write_text('schema_version = 1\n')
        return path

    def test_cli_defaults_and_selection(self) -> None:
        args = _parser().parse_args(['config', 'model-presets'])
        self.assertEqual(args.scope, 'project')
        self.assertIsNone(args.target)
        self.assertIsNone(args.preset)
        self.assertFalse(args.dry_run)
        args = _parser().parse_args(['config', 'model-presets', '--preset', 'quality', '--dry-run'])
        self.assertEqual(args.preset, 'quality')
        self.assertTrue(args.dry_run)
        with patch('agent_team.cli.project_root', return_value=self.root), patch(
            'agent_team.cli.edit_model_presets', return_value=0,
        ) as editor:
            self.assertEqual(main(['config', 'model-presets']), 0)
            editor.assert_called_once_with(self.root, scope='project', target=None, preset=None, dry_run=False)

    def test_single_preset_sparse_save_and_comments(self) -> None:
        before = self.routing('economy')
        self.assertEqual(self.edit(['new'] + [''] * 7 + ['yes']), 0)
        self.assertEqual(self.routing().coordinator_model, 'new')
        self.assertEqual(self.routing('economy'), before)
        text = self.path.read_text()
        self.assertIn('# keep comment', text)
        data = tomllib.loads(text)['model_presets']['codex']
        self.assertEqual(set(data), {'balanced'})
        self.assertIn('agent-team install --scope project --target codex --apply', self.output[-1])

    def test_default_all_presets(self) -> None:
        answers = iter((['new'] + [''] * 7) * 3 + ['yes'])
        edit_model_presets(self.root, target='codex', read=lambda _: next(answers), emit=self.output.append)
        self.assertEqual(set(tomllib.loads(self.path.read_text())['model_presets']['codex']),
                         {'economy', 'balanced', 'quality'})

    def test_dry_run_and_default_no(self) -> None:
        before = self.path.read_bytes()
        self.edit(['new'] + [''] * 7, dry_run=True)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIn('--- ', '\n'.join(self.output))
        self.edit(['new'] + [''] * 7 + [''])
        self.assertEqual(self.path.read_bytes(), before)
        self.edit(['new'] + [''] * 7 + ['y'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_eof_and_interrupt_no_mutation(self) -> None:
        before = self.path.read_bytes()
        for error in (EOFError, KeyboardInterrupt):
            with self.subTest(error=error), patch('builtins.input', side_effect=error):
                self.assertEqual(edit_model_presets(self.root, target='codex', preset='balanced',
                                                    emit=self.output.append), 0)
            self.assertEqual(self.path.read_bytes(), before)

    def test_all_catalogs_preflight_before_prompt(self) -> None:
        unavailable = CatalogResult('claude', 'api', 'unavailable', (), 'missing key')
        with patch('agent_team.config_editor.fetch_catalog', side_effect=[self.catalog, unavailable]) as fetch, self.assertRaisesRegex(ValidationFailure, 'missing key'):
            edit_model_presets(self.root, target='codex,claude', read=lambda _: self.fail('prompted'))
        self.assertEqual(fetch.call_count, 2)
        self.assertNotIn('model_presets', self.path.read_text())

    def test_target_selection_detects_enabled_installed_clients(self) -> None:
        config = load_team_config(self.root)
        with patch('agent_team.config_editor.shutil.which', side_effect=lambda name: '/client' if name == 'agy' else None):
            self.assertEqual(select_targets(config, None), ('antigravity',))
            with self.assertRaises(ValidationFailure):
                select_targets(config, 'codex')
        for target in ('unknown', 'codex,codex', '', 'codex,'):
            with self.subTest(target=target), self.assertRaises(ValidationFailure):
                select_targets(config, target)

    def test_missing_configuration_does_not_initialize(self) -> None:
        self.path.unlink()
        with self.assertRaisesRegex(ValidationFailure, 'cannot read'):
            self.edit([])
        self.assertFalse(self.path.exists())

    def test_invalid_default_requires_explicit_selection(self) -> None:
        catalog = CatalogResult('codex', 'test', 'ok', ({'model_id': 'new', 'effort_options': ['high']},))
        with patch('agent_team.config_editor.fetch_catalog', return_value=catalog):
            self.edit(['', '1', '1', '1', '1', '1', '1', '1', '1', 'yes'])
        self.assertEqual(self.routing().coordinator_effort, 'high')
        self.assertIn('Enter a listed number or value.', self.output)

    def test_unknown_effort_metadata_uses_labeled_fallback(self) -> None:
        catalog = CatalogResult('codex', 'test', 'ok', ({'model_id': 'new', 'effort_options': None},))
        with patch('agent_team.config_editor.fetch_catalog', return_value=catalog):
            self.edit(['1'] * 4 + [''] * 4 + ['yes'])
        self.assertIn('using profile effort levels', '\n'.join(self.output))

    def test_efforts_intersect_all_worker_models(self) -> None:
        models = list(self.catalog.models)
        models[0] = {**models[0], 'effort_options': ['medium']}
        with patch('agent_team.config_editor.fetch_catalog', return_value=CatalogResult('codex', 'test', 'ok', tuple(models))):
            self.edit(['', 'new', '', '', '', 'medium', '', 'medium', 'yes'])
        self.assertEqual(set(self.routing().effort.values()), {'medium'})

    def test_explicit_no_effort_coordinator_rejected(self) -> None:
        catalog = CatalogResult('codex', 'test', 'ok', ({'model_id': 'new', 'effort_options': []},))
        before = self.path.read_bytes()
        with patch('agent_team.config_editor.fetch_catalog', return_value=catalog), self.assertRaisesRegex(ValidationFailure, 'coordinator schema requires effort'):
            self.edit(['1'] * 4)
        self.assertEqual(self.path.read_bytes(), before)

    def test_explicit_no_effort_worker_requires_profile_exemption(self) -> None:
        models = list(self.catalog.models)
        models[0] = {**models[0], 'effort_options': []}
        with patch('agent_team.config_editor.fetch_catalog', return_value=CatalogResult('codex', 'test', 'ok', tuple(models))), self.assertRaisesRegex(ValidationFailure, 'no compatible choices'):
            self.edit(['', 'new', '', '', ''])
        path = self.file_profile()
        path.write_text(path.read_text().replace('models_without_effort = []', 'models_without_effort = ["new"]'))
        with patch('agent_team.config_editor.fetch_catalog', return_value=CatalogResult('codex', 'test', 'ok', tuple(models))):
            self.edit(['', 'new', '', '', ''] + [''] * 3 + ['yes'])
        self.assertEqual(self.routing().models['fast'], 'new')

    def test_file_profile_edits_preserve_comments_and_team(self) -> None:
        path = self.file_profile()
        before = self.path.read_bytes()
        self.edit(['new'] + [''] * 7 + ['yes'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIn('# profile comment', path.read_text())
        self.assertEqual(self.routing().coordinator_model, 'new')

    def test_inherited_profile_copy_and_masking_override(self) -> None:
        path = self.file_profile(inherited=True)
        user_path = self.user / 'team.toml'
        user_path.write_text(user_path.read_text() + '\n[model_presets.codex.balanced]\ncoordinator_model = "gpt-6-sol"\n')
        before_profile, before_config = path.read_bytes(), user_path.read_bytes()
        self.edit(['new'] + [''] * 7 + ['yes'])
        self.assertEqual(path.read_bytes(), before_profile)
        self.assertEqual(user_path.read_bytes(), before_config)
        self.assertEqual(self.routing().coordinator_model, 'new')
        local = self.root / '.agent-team/profiles/codex.toml'
        self.assertTrue(local.exists())
        data = tomllib.loads(self.path.read_text())
        self.assertEqual(data['target_profiles']['codex'], '.agent-team/profiles/codex.toml')
        self.assertEqual(data['model_presets']['codex']['balanced']['coordinator_model'], 'new')

    def test_local_profile_masked_overrides_synchronized(self) -> None:
        path = self.file_profile()
        self.path.write_text(self.path.read_text() + '\n[model_presets.codex.balanced]\ncoordinator_model = "gpt-6-sol"\n')
        self.edit(['new'] + [''] * 7 + ['yes'])
        self.assertEqual(self.routing().coordinator_model, 'new')
        self.assertEqual(tomllib.loads(path.read_text())['presets']['balanced']['coordinator_model'], 'new')

    def test_user_scope_does_not_touch_project(self) -> None:
        user_path = self.user / 'team.toml'
        user_path.write_text('schema_version = 1\n')
        before = self.path.read_bytes()
        self.edit(['new'] + [''] * 7 + ['yes'], scope='user')
        self.assertEqual(self.path.read_bytes(), before)
        config = load_user_config()
        self.assertEqual(resolve_target_profile(config, 'codex', self.user).presets['balanced'].coordinator_model, 'new')

    def test_stale_original_detected_after_confirmation(self) -> None:
        answers = iter(['new'] + [''] * 7)
        def read(prompt: str) -> str:
            if prompt.startswith('Save'):
                self.path.write_text(self.path.read_text() + '# external edit\n')
                return 'yes'
            return next(answers)
        with self.assertRaisesRegex(ValidationFailure, 'changed since preview'):
            edit_model_presets(self.root, target='codex', preset='balanced', read=read, emit=self.output.append)
        self.assertNotIn('model_presets', self.path.read_text())
        self.assertIn('# external edit', self.path.read_text())

    def test_symlink_destination_rejected(self) -> None:
        original = self.path.read_text()
        destination = self.root / 'original.toml'
        destination.write_text(original)
        self.path.unlink()
        self.path.symlink_to(destination)
        with self.assertRaisesRegex(ValidationFailure, 'symlink'):
            self.edit([])
        self.assertEqual(destination.read_text(), original)

    def test_rollback_existing_and_new_files(self) -> None:
        existing = self.root / 'existing.toml'
        new = self.root / 'new.toml'
        existing.write_text('old')
        existing.chmod(0o640)
        last = self.root / 'last.toml'
        candidates = (
            Candidate(existing, 'old', 'edited', self.root),
            Candidate(new, None, 'new', self.root),
            Candidate(last, None, 'last', self.root),
        )
        def write(path: Path, content: str) -> None:
            if path == last:
                raise OSError('write failed')
            atomic_write(path, content)
        with patch('agent_team.config_editor.atomic_write', side_effect=write), self.assertRaisesRegex(ValidationFailure, 'earlier writes restored'):
            apply_candidates(candidates, {existing: 'old'})
        self.assertEqual(existing.read_text(), 'old')
        self.assertEqual(existing.stat().st_mode & 0o777, 0o640)
        self.assertFalse(new.exists())
        self.assertFalse(last.exists())

    def test_interrupt_after_replacement_restores_current_and_earlier_files(self) -> None:
        for original in ('old', None):
            with self.subTest(original=original):
                earlier = self.root / 'earlier.toml'
                current = self.root / 'interrupted.toml'
                earlier.write_text('earlier original')
                if original is not None:
                    current.write_text(original)
                    current.chmod(0o640)
                candidates = (
                    Candidate(earlier, 'earlier original', 'earlier edited', self.root),
                    Candidate(current, original, 'current edited', self.root),
                )
                def write(path: Path, content: str, interrupted_path: Path = current) -> None:
                    atomic_write(path, content)
                    if path == interrupted_path and content == 'current edited':
                        raise KeyboardInterrupt
                with patch('agent_team.config_editor.atomic_write', side_effect=write), self.assertRaisesRegex(ValidationFailure, 'earlier writes restored'):
                    apply_candidates(candidates, {})
                self.assertEqual(earlier.read_text(), 'earlier original')
                if original is None:
                    self.assertFalse(current.exists())
                else:
                    self.assertEqual(current.read_text(), original)
                    self.assertEqual(current.stat().st_mode & 0o777, 0o640)
                    current.unlink()

    def test_interrupt_before_replacement_keeps_original_or_absent_file(self) -> None:
        for original in ('old', None):
            with self.subTest(original=original):
                current = self.root / 'interrupted.toml'
                if original is not None:
                    current.write_text(original)
                candidate = Candidate(current, original, 'edited', self.root)
                with patch('agent_team.config_editor.atomic_write', side_effect=KeyboardInterrupt) as write, self.assertRaisesRegex(ValidationFailure, 'earlier writes restored'):
                    apply_candidates((candidate,), {})
                write.assert_called_once_with(current, 'edited')
                if original is None:
                    self.assertFalse(current.exists())
                else:
                    self.assertEqual(current.read_text(), original)
                    current.unlink()

    def test_repeated_interrupt_during_rollback_reports_failure_and_continues(self) -> None:
        earlier = self.root / 'earlier.toml'
        current = self.root / 'interrupted.toml'
        earlier.write_text('earlier original')
        current.write_text('current original')
        candidates = (
            Candidate(earlier, 'earlier original', 'earlier edited', self.root),
            Candidate(current, 'current original', 'current edited', self.root),
        )
        calls: list[tuple[Path, str]] = []
        def write(path: Path, content: str) -> None:
            calls.append((path, content))
            atomic_write(path, content)
            if path == current:
                raise KeyboardInterrupt
        with patch('agent_team.config_editor.atomic_write', side_effect=write), self.assertRaisesRegex(ValidationFailure, 'rollback failed:.*recovery interrupted; verify file contents'):
            apply_candidates(candidates, {})
        self.assertEqual(current.read_text(), 'current original')
        self.assertEqual(earlier.read_text(), 'earlier original')
        self.assertIn((earlier, 'earlier original'), calls)

    def test_rollback_preserves_external_contents(self) -> None:
        for original in ('old', None):
            with self.subTest(original=original):
                current = self.root / 'interrupted.toml'
                if original is not None:
                    current.write_text(original)
                candidate = Candidate(current, original, 'edited', self.root)
                def write(path: Path, content: str) -> None:
                    atomic_write(path, content)
                    path.write_text('external contents')
                    raise KeyboardInterrupt
                with patch('agent_team.config_editor.atomic_write', side_effect=write), self.assertRaisesRegex(ValidationFailure, 'preserved external contents'):
                    apply_candidates((candidate,), {})
                self.assertEqual(current.read_text(), 'external contents')
                current.unlink()

    def test_candidate_validation_precedes_preview(self) -> None:
        before = self.path.read_bytes()
        with patch('agent_team.config_editor.upsert_strings', return_value='schema_version = "invalid"\n'), self.assertRaises(ValidationFailure):
            self.edit(['new'] + [''] * 7)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(any(item.startswith('---') for item in self.output))

    def test_catalog_interrupt_returns_cleanly(self) -> None:
        before = self.path.read_bytes()
        with patch('agent_team.config_editor.fetch_catalog', side_effect=KeyboardInterrupt):
            self.assertEqual(self.edit([]), 0)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.output[-1], 'Cancelled: no files saved.')

    def test_escaping_candidate_rejected(self) -> None:
        outside = self.user / 'outside.toml'
        with self.assertRaisesRegex(ValidationFailure, 'escapes selected scope'):
            apply_candidates((Candidate(outside, None, 'unsafe', self.root),), {})
        self.assertFalse(outside.exists())

    def test_existing_inherited_copy_destination_rejected(self) -> None:
        original = self.file_profile(inherited=True)
        copy = self.root / '.agent-team/profiles/codex.toml'
        copy.parent.mkdir()
        copy.write_text('unrelated')
        before = original.read_bytes()
        with self.assertRaisesRegex(ValidationFailure, 'already exists'):
            self.edit(['new'] + [''] * 7)
        self.assertEqual(copy.read_text(), 'unrelated')
        self.assertEqual(original.read_bytes(), before)

    def test_disabled_targets_rejected(self) -> None:
        self.path.write_text(self.path.read_text() + 'enabled_targets = ["claude"]\n')
        with self.assertRaisesRegex(ValidationFailure, 'must be enabled'):
            self.edit([])

    def test_new_destination_conflict_detected(self) -> None:
        new = self.root / 'new.toml'
        new.write_text('external')
        with self.assertRaisesRegex(ValidationFailure, 'changed since preview'):
            apply_candidates((Candidate(new, None, 'candidate', self.root),), {})
        self.assertEqual(new.read_text(), 'external')

    def test_repeat_noop_preserves_content(self) -> None:
        self.edit(['new'] + [''] * 7 + ['yes'])
        before = self.path.read_bytes()
        self.edit([''] * 8)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.output[-1], 'No model preset changes.')

    def test_cli_error_is_actionable(self) -> None:
        with patch('agent_team.cli.project_root', return_value=self.root), redirect_stdout(io.StringIO()), patch('sys.stderr', new_callable=io.StringIO) as stderr:
            self.assertEqual(main(['config', 'model-presets', '--target', 'unknown']), 2)
        self.assertIn('unsupported target', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
