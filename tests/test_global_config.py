from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_team.adapters import load_skills
from agent_team.config import (
    DEFAULT_TEAM_TOML,
    load_roles,
    load_team_config,
    load_user_config,
    parse_target_profile,
    parse_team_config,
    project_init_toml,
    resolve_target_profile,
    user_init_toml,
)
from agent_team.diagnostics import ValidationFailure


class GlobalConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.project = self.root / 'project'
        self.user = self.home / '.agent-team'
        self.user.mkdir(parents=True)
        (self.project / '.agent-team').mkdir(parents=True)
        self.patch = patch('pathlib.Path.home', return_value=self.home)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.write_project(project_init_toml())

    def write_project(self, text):
        (self.project / '.agent-team/team.toml').write_text(text)

    def write_user(self, text):
        (self.user / 'team.toml').write_text(text)

    def test_live_sparse_nested_merge_and_array_replacement(self):
        self.write_user('enabled_targets = ["codex"]\n[model_presets.codex.balanced.models]\nfast = "user-fast"\ndeep = "user-deep"\n[workflow]\nreview_cycle_limit = 3\n')
        self.write_project('schema_version = 1\n[model_presets.codex.balanced.models]\nfast = "project-fast"\n')
        config = load_team_config(self.project)
        self.assertEqual(config.enabled_targets, ('codex',))
        self.assertEqual(config.workflow.review_cycle_limit, 3)
        profile = resolve_target_profile(config, 'codex', self.project)
        self.assertEqual(profile.presets['balanced'].models['fast'], 'project-fast')
        self.assertEqual(profile.presets['balanced'].models['deep'], 'user-deep')
        self.assertEqual(config.field_origins['model_presets.codex.balanced.models.fast'], 'project')
        self.assertEqual(config.field_origins['model_presets.codex.balanced.models.deep'], 'user')
        self.write_user('enabled_targets = ["claude"]')
        self.assertEqual(load_team_config(self.project).enabled_targets, ('claude',))

    def test_opt_out_bypasses_malformed_user_and_missing_project_fails(self):
        self.write_user('malformed = [')
        self.write_project(project_init_toml(isolated=True))
        self.assertFalse(load_team_config(self.project).inherit_user_defaults)
        self.write_project(project_init_toml())
        with self.assertRaises(ValidationFailure):
            load_team_config(self.project)
        (self.project / '.agent-team/team.toml').unlink()
        self.write_user(DEFAULT_TEAM_TOML)
        with self.assertRaises(ValidationFailure):
            load_team_config(self.project)

    def test_every_layer_rejects_explicit_invalid_values_before_masking(self):
        invalid = ('name = 3', 'bogus = true', '[workflow]\nreview_cycle_limit = "bad"',
                   'role_sources = ["builtin:bogus"]', '[target_profiles]\ncodex = "builtin:claude"',
                   '[model_presets.codex.balanced.models]\nfast = 5',
                   '[tiers.team]\nmax_workers = true', 'inherit_user_defaults = "true"')
        for text in invalid:
            with self.subTest(text=text):
                self.write_user(text)
                self.write_project(DEFAULT_TEAM_TOML)
                with self.assertRaises(ValidationFailure):
                    load_team_config(self.project)
                self.write_user('')
                self.write_project(text)
                with self.assertRaises(ValidationFailure):
                    load_team_config(self.project)

    def test_custom_profiles_keep_defining_scope_and_project_override(self):
        builtin = Path('src/agent_team/assets/definitions/targets/codex.toml').read_text()
        (self.user / 'profile.toml').write_text(builtin.replace('gpt-5.6-terra', 'user-model'))
        self.write_user('[target_profiles]\ncodex = "profile.toml"')
        config = load_team_config(self.project)
        self.assertEqual(config.target_profile_roots['codex'], self.user)
        self.assertEqual(config.field_origins['target_profiles.codex'], 'user')
        self.assertIn('user-model', resolve_target_profile(config, 'codex', self.project).presets['balanced'].models.values())
        (self.project / 'profile.toml').write_text(builtin)
        self.write_project('[target_profiles]\ncodex = "profile.toml"')
        config = load_team_config(self.project)
        self.assertEqual(config.target_profile_roots['codex'], self.project)
        self.assertEqual(config.field_origins['target_profiles.codex'], 'project')

    def make_role(self, scope, text):
        directory = scope / 'roles/implementer'
        directory.mkdir(parents=True, exist_ok=True)
        builtin = Path('src/agent_team/assets/definitions/roles/implementer/role.toml')
        (directory / 'role.toml').write_text(builtin.read_text())
        (directory / 'instructions.md').write_text(text)

    def make_skill(self, scope, text):
        directory = scope / 'skills/team-plan'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'SKILL.md').write_text(text)

    def test_named_definitions_replace_whole_ids_and_builtins_seed_once(self):
        self.make_role(self.user, 'user instructions')
        self.make_role(self.project, 'project instructions')
        self.make_skill(self.user, 'user skill')
        self.make_skill(self.project, 'project skill')
        self.write_user('role_sources = ["roles", "builtin:roles"]\nskill_sources = ["skills", "builtin:skills"]')
        config = load_team_config(self.project)
        roles = {role.role_id: role for role in load_roles(config, self.project)}
        self.assertEqual(roles['implementer'].instructions, 'user instructions')
        self.assertIn(str(self.user), roles['implementer'].source)
        self.assertEqual(dict(load_skills(config, self.project))['team-plan'], 'user skill')
        self.write_project('role_sources = ["roles", "builtin:roles"]\nskill_sources = ["skills", "builtin:skills"]')
        config = load_team_config(self.project)
        self.assertEqual({r.role_id: r for r in load_roles(config, self.project)}['implementer'].instructions, 'project instructions')
        self.assertEqual(dict(load_skills(config, self.project))['team-plan'], 'project skill')
        self.assertEqual(config.role_sources, ('roles', 'builtin:roles'))

    def test_source_and_nested_symlinks_cannot_escape_scope(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.user / 'escape').symlink_to(outside, target_is_directory=True)
        for text in ('role_sources = ["escape"]', 'skill_sources = ["../outside"]', '[target_profiles]\ncodex = "escape/profile.toml"'):
            self.write_user(text)
            with self.assertRaises(ValidationFailure):
                load_team_config(self.project)
        self.make_skill(self.user, 'original')
        escaped = outside / 'SKILL.md'
        escaped.write_text('escaped')
        skill = self.user / 'skills/team-plan/SKILL.md'
        skill.unlink()
        skill.symlink_to(escaped)
        self.write_user('skill_sources = ["skills"]')
        with self.assertRaises(ValidationFailure):
            load_skills(load_team_config(self.project), self.project)
        self.make_role(self.user, 'original')
        instruction = self.user / 'roles/implementer/instructions.md'
        instruction.unlink()
        instruction.symlink_to(escaped)
        self.write_user('role_sources = ["roles"]')
        with self.assertRaises(ValidationFailure):
            load_roles(load_team_config(self.project), self.project)

    def test_run_root_remains_project_relative(self):
        self.write_user('[workflow]\nrun_root = "runs"')
        config = load_team_config(self.project)
        self.assertEqual(config.workflow.run_root, Path('runs'))
        self.assertEqual(config.field_origins['workflow.run_root'], 'user')

    def test_user_loader_requires_prior_setup_and_ignores_project(self):
        with self.assertRaises(ValidationFailure) as error:
            load_user_config()
        self.assertIn('init --scope user', str(error.exception))
        self.write_user('name = "Personal team"')
        self.write_project('name = "Project team"')
        self.assertEqual(load_user_config().name, 'Personal team')

    def test_templates_and_commented_examples_are_valid(self):
        text = user_init_toml()
        parse_team_config(tomllib.loads(text), self.user)
        self.write_project(project_init_toml())
        load_team_config(self.project)
        parse_team_config(tomllib.loads(project_init_toml(isolated=True)), self.project)
        for target in ('codex', 'claude', 'antigravity'):
            marker = f'# --- Complete {target} profile example ({target}.toml) ---\n'
            example = text.split(marker, 1)[1].split(f'# --- Sparse {target}', 1)[0]
            uncommented = '\n'.join(line.removeprefix('# ') if line.startswith('# ') else '' for line in example.splitlines())
            parse_target_profile(tomllib.loads(uncommented), target)
            preset_examples = text.split(f'# --- Sparse {target} model preset override examples ---\n', 1)[1].split('# --- Complete ', 1)[0]
            uncommented = '\n'.join(line.removeprefix('# ') if line.startswith('# ') else '' for line in preset_examples.splitlines())
            self.write_user(uncommented)
            resolve_target_profile(load_user_config(), target, self.user)


if __name__ == '__main__':
    unittest.main()
